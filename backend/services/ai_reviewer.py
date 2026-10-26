"""Import an AI-enhanced collection from the AI reviewer (mediacloud-ai-reviewer) and send the decisions back.

The AI reviewer publishes, per collection, a JSON document (schema mediacloud-ai-review/1, see its docs/API.md):
every source with the AI's decision, reason and evidence. Importing it creates a ReviewProject in which
- the AI's clear calls (keep / remove / skip / add) arrive filled in, with the AI's reason as removal_reason or
  skip_note and no decided_at, so a person's later decision is recognisable;
- what the AI left for people arrives undecided and is spread evenly over the reviewer queues;
- additions arrive as new sources. They carry their Media Cloud source id when the outlet is already in the
  directory, so publishing attaches that source instead of creating a duplicate.
Proposed collections that Media Cloud does not have yet (no collection id) can be imported too.

The reviewers' decisions go back with send_decisions() (schema mediacloud-ai-review-decisions/1).
"""
import json
import uuid

import requests

from config import get_config
from database import db
from models import Decision, Review, ReviewItem, ReviewProject, ReviewProjectSource

SCHEMA = 'mediacloud-ai-review/1'
DECISIONS_SCHEMA = 'mediacloud-ai-review-decisions/1'
SKIP_NOTE_MAX_LEN = 4000
_DECISIONS = {
    'keep': Decision.KEEP,
    'remove': Decision.REMOVE,
    'skip': Decision.SKIP,
    'add': Decision.ADD,
    'undecided': Decision.UNDECIDED,
}
# Media Cloud source fields kept as the item's source_metadata (what the exports and the reviewer screen read)
MC_FIELDS = (
    'homepage', 'domain', 'url_search_string', 'label', 'notes', 'platform', 'pub_country', 'pub_state',
    'media_type', 'stories_total', 'stories_per_week', 'last_story', 'primary_language',
)


def _headers():
    token = get_config().AI_REVIEWER_TOKEN
    return {'Authorization': f'Bearer {token}'} if token else {}


def fetch_proposal(url):
    response = requests.get(url, headers=_headers(), timeout=120)
    response.raise_for_status()
    return response.json()


def validate(proposal):
    if not isinstance(proposal, dict) or proposal.get('schema') != SCHEMA:
        raise ValueError(f'Not an AI review: expected a document with schema "{SCHEMA}"')
    if not isinstance(proposal.get('items'), list) or not proposal['items']:
        raise ValueError('The AI review has no items')


def _is_new(item):
    return bool(item.get('is_new_source')) or not item.get('source_id')


def _metadata(item):
    metadata = {k: item.get(k) for k in MC_FIELDS if item.get(k) not in (None, '')}
    if item.get('source_id'):
        metadata['id'] = item['source_id']
    return metadata


def _ai(item):
    return dict(item.get('ai') or {}, key=item.get('key'))


def _is_open(ai):
    return (ai or {}).get('decision') == 'undecided'


def create_project(proposal, source_url=None, name=None, edit_metadata=False):
    """Create the ReviewProject and its seed sources (existing sources; additions become items with the queues).
    The caller commits."""
    validate(proposal)
    collection = proposal.get('collection') or {}
    collection_id = collection.get('id')
    label = collection.get('name') or collection.get('key') or 'AI review'
    project = ReviewProject(
        guid=str(uuid.uuid4()),
        collection_ids_json=json.dumps([int(collection_id)] if collection_id else []),
        collection_names_json=json.dumps([label]),
        name=(name or f"{label} - AI review {(proposal.get('generated_at') or '')[:10]}").strip(),
        notes=f"Imported from the AI reviewer: {source_url or 'uploaded file'}",
        guidelines_template='default',
        guidelines_custom_markdown=proposal.get('guidelines_markdown') or None,
        edit_metadata=bool(edit_metadata),
        ai_source_url=source_url,
        ai_callback_url=(proposal.get('callback') or {}).get('decisions_url') or None,
        ai_proposal_json=json.dumps(proposal),
    )
    db.session.add(project)
    db.session.flush()
    existing = 0
    for item in proposal['items']:
        if _is_new(item):
            continue
        db.session.add(ReviewProjectSource(
            review_project_id=project.id,
            source_id=int(item['source_id']),
            source_label=item.get('label') or '',
            source_homepage=item.get('homepage') or '',
            source_metadata=json.dumps(_metadata(item)),
            ai_json=json.dumps(_ai(item)),
        ))
        existing += 1
    return project, existing, sum(1 for i in proposal['items'] if _is_new(i))


def new_source_count(project):
    if not project.ai_proposal_json:
        return 0
    return sum(1 for i in json.loads(project.ai_proposal_json).get('items', []) if _is_new(i))


def order_for_queues(sources):
    """Seed sources with the items left for people first, so round-robin spreads them evenly over the queues."""
    def open_first(source):
        return (not _is_open(json.loads(source.ai_json)) if source.ai_json else True, source.id)
    return sorted(sources, key=open_first)


def apply_ai(item, ai):
    """Fill a queue item with the AI's proposal: its decision (without decided_at) and the reason as the note."""
    item.ai_json = json.dumps(ai)
    decision = _DECISIONS.get(ai.get('decision'), Decision.UNDECIDED)
    if not item.is_new_source and decision == Decision.ADD:
        decision = Decision.KEEP
    item.decision = decision
    note = ai.get('note') or ai.get('reason') or ''
    if decision == Decision.REMOVE:
        item.removal_reason = note or 'AI reviewer: does not meet the collection guidelines'
    elif decision == Decision.SKIP:
        item.skip_note = note[:SKIP_NOTE_MAX_LEN] or None


def add_new_source_items(project, queues, start=0):
    """The proposal's additions as new-source items, those left for people first, round-robin from queue `start`."""
    if not project.ai_proposal_json or not queues:
        return 0
    new = [i for i in json.loads(project.ai_proposal_json).get('items', []) if _is_new(i)]
    new.sort(key=lambda i: not _is_open(i.get('ai')))
    for n, entry in enumerate(new):
        queue = queues[(start + n) % len(queues)]
        item = ReviewItem(
            review_id=queue.id,
            source_id=int(entry['source_id']) if entry.get('source_id') else None,
            source_label=entry.get('label') or entry.get('domain') or '',
            source_homepage=entry.get('homepage') or '',
            is_new_source=True,
            decision=Decision.ADD,
            source_metadata=json.dumps(_metadata(entry)),
        )
        apply_ai(item, _ai(entry))
        db.session.add(item)
    return len(new)


def collect_decisions(project, project_url=None):
    """Every item's current decision, in the AI reviewer's decisions format."""
    queue_ids = [q.id for q in Review.query.filter_by(review_project_id=project.id).all()]
    items = ReviewItem.query.filter(ReviewItem.review_id.in_(queue_ids)).order_by(ReviewItem.id.asc()).all() \
        if queue_ids else []
    decisions = []
    for item in items:
        ai = json.loads(item.ai_json) if item.ai_json else {}
        decisions.append({
            'key': ai.get('key'),
            'source_id': item.source_id,
            'is_new_source': bool(item.is_new_source),
            'homepage': item.source_homepage or '',
            'label': item.source_label or '',
            'decision': item.decision.value if item.decision else 'undecided',
            'removal_reason': item.removal_reason or '',
            'skip_note': item.skip_note or '',
            'ai_decision': ai.get('decision'),
            'decided_at': item.decided_at.isoformat() if item.decided_at else '',
        })
    proposal = json.loads(project.ai_proposal_json) if project.ai_proposal_json else {}
    return {
        'schema': DECISIONS_SCHEMA,
        'collection_key': (proposal.get('collection') or {}).get('key'),
        'project': {'guid': project.guid, 'name': project.name, 'url': project_url},
        'decisions': decisions,
    }


def send_decisions(project, project_url=None):
    if not project.ai_callback_url:
        raise ValueError('This project was not imported from the AI reviewer, or its review had no callback address')
    response = requests.post(project.ai_callback_url, json=collect_decisions(project, project_url),
                             headers=_headers(), timeout=120)
    if response.status_code >= 400:
        raise RuntimeError(f'The AI reviewer answered {response.status_code}: {response.text[:300]}')
    return response.json()
