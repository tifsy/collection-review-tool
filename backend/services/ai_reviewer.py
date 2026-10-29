"""Import an AI review from the collection AI reviewer (mediacloud-ai-reviewer) and send the decisions back.

The AI reviewer publishes, per collection, a JSON document (schema mediacloud-ai-review/1): every source with
the AI's decision, reason and evidence. Importing it creates a ReviewProject in which
- the AI's clear calls (keep / remove / skip / add) arrive filled in, with the AI's reason as removal_reason or
  skip_note and no decided_at, so a reviewer's later decision is recognisable;
- what the AI left for people arrives undecided and is spread evenly over the reviewer queues;
- additions arrive as new sources. They carry their Media Cloud source id when the outlet is already in the
  directory, so publishing attaches that source instead of creating a duplicate.
Proposed collections that Media Cloud does not have yet (no collection id) can be imported too.

The reviewers' decisions go back with send_decisions() (schema mediacloud-ai-review-decisions/1).

The backend only talks to the AI reviewer at AI_REVIEWER_BASE_URL: AI reviews are fetched, and decisions sent,
only from and to addresses under it, redirects are not followed, and AI_REVIEWER_TOKEN is never sent elsewhere.
"""
import json
import uuid
from urllib.parse import urlsplit

import requests

from config import get_config
from database import db
from models import Decision, Review, ReviewItem, ReviewProject, ReviewProjectSource

SCHEMA = 'mediacloud-ai-review/1'
DECISIONS_SCHEMA = 'mediacloud-ai-review-decisions/1'
REQUEST_TIMEOUT = 60
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


# ── Trusted AI reviewer address ────────────────────────────────────────────────

def _split_url(url):
    """(origin, path) of an absolute http(s) URL, or None for anything unusual."""
    if not isinstance(url, str) or '\\' in url or any(c.isspace() for c in url):
        return None
    try:
        parts = urlsplit(url)
        port = parts.port or (443 if parts.scheme == 'https' else 80)
    except ValueError:
        return None
    if parts.scheme not in ('http', 'https') or not parts.hostname or parts.username or parts.password:
        return None
    if '..' in parts.path.split('/'):
        return None
    return (parts.scheme, parts.hostname.lower(), port), parts.path


def base_url():
    return (get_config().AI_REVIEWER_BASE_URL or '').strip()


def is_trusted_url(url):
    """True when `url` is under AI_REVIEWER_BASE_URL: same scheme, host and port, and within its path."""
    base = _split_url(base_url())
    target = _split_url(url)
    if not base or not target or base[0] != target[0]:
        return False
    base_path = base[1].rstrip('/')
    return target[1] == base_path or target[1].startswith(base_path + '/')


def _headers(url):
    token = get_config().AI_REVIEWER_TOKEN
    return {'Authorization': f'Bearer {token}'} if token and is_trusted_url(url) else {}


def _require_trusted(url, what):
    if not base_url():
        raise ValueError(f'{what} needs AI_REVIEWER_BASE_URL to be configured')
    if not is_trusted_url(url):
        raise ValueError(f'{what} is only allowed for addresses under {base_url()}')


# ── Import ─────────────────────────────────────────────────────────────────────

def fetch_proposal(url):
    _require_trusted(url, 'Importing an AI review by URL')
    response = requests.get(url, headers=_headers(url), timeout=REQUEST_TIMEOUT, allow_redirects=False)
    if response.is_redirect:
        raise ValueError('The AI reviewer answered with a redirect, which is not followed')
    response.raise_for_status()
    try:
        return response.json()
    except ValueError:
        raise ValueError('The AI reviewer did not answer with JSON')


def validate(proposal):
    if not isinstance(proposal, dict) or proposal.get('schema') != SCHEMA:
        raise ValueError(f'Not an AI review: expected a document with schema "{SCHEMA}"')
    if not isinstance(proposal.get('items'), list) or not proposal['items']:
        raise ValueError('The AI review has no items')
    if not all(isinstance(item, dict) for item in proposal['items']):
        raise ValueError('The AI review has malformed items')


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
    """Create the ReviewProject and its seed sources (the AI's new sources become items with the queues).
    Returns (project, existing_count, new_count, warnings). The caller commits."""
    validate(proposal)
    warnings = []
    collection = proposal.get('collection') or {}
    collection_id = collection.get('id')
    label = collection.get('name') or collection.get('key') or 'AI review'

    callback_url = (proposal.get('callback') or {}).get('decisions_url') or None
    if callback_url and not is_trusted_url(callback_url):
        warnings.append(
            'The AI review asks for decisions to be sent to an address outside AI_REVIEWER_BASE_URL; '
            'it was ignored. Download the decisions as JSON instead.'
        )
        callback_url = None

    project = ReviewProject(
        guid=str(uuid.uuid4()),
        collection_ids_json=json.dumps([int(collection_id)] if collection_id else []),
        collection_names_json=json.dumps([label]),
        name=(name or f"{label} · AI review {(proposal.get('generated_at') or '')[:10]}").strip(),
        notes=f"Imported from the AI reviewer: {source_url or 'uploaded JSON'}",
        guidelines_template='default',
        guidelines_custom_markdown=proposal.get('guidelines_markdown') or None,
        edit_metadata=bool(edit_metadata),
        ai_source_url=source_url,
        ai_callback_url=callback_url,
        ai_proposal_json=json.dumps(proposal),
    )
    db.session.add(project)
    db.session.flush()

    seen = set()
    for item in proposal['items']:
        if _is_new(item):
            continue
        source_id = int(item['source_id'])
        if source_id in seen:
            continue
        seen.add(source_id)
        db.session.add(ReviewProjectSource(
            review_project_id=project.id,
            source_id=source_id,
            source_label=item.get('label') or '',
            source_homepage=item.get('homepage') or '',
            source_metadata=json.dumps(_metadata(item)),
            ai_json=json.dumps(_ai(item)),
        ))
    new_count = len(new_source_entries(project))
    return project, len(seen), new_count, warnings


# ── Queue generation ───────────────────────────────────────────────────────────

def new_source_entries(project):
    """The AI review's additions (dicts), which become new-source items when the queues are generated."""
    if not project.ai_proposal_json:
        return []
    return [i for i in json.loads(project.ai_proposal_json).get('items', []) if _is_new(i)]


def order_for_queues(entries):
    """Items the AI left for people first, so round-robin spreads them evenly over the queues.
    Stable: projects not imported from the AI reviewer keep their order."""
    def ai_of(entry):
        if isinstance(entry, dict):
            return entry.get('ai')
        return json.loads(entry.ai_json) if entry.ai_json else None
    return sorted(entries, key=lambda entry: not _is_open(ai_of(entry)))


def apply_ai(item, ai):
    """Fill a queue item with the AI's call: its decision (without decided_at) and its reason as the note."""
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


def new_source_item(review_id, entry):
    """A new-source queue item for one of the AI review's additions."""
    item = ReviewItem(
        review_id=review_id,
        source_id=int(entry['source_id']) if entry.get('source_id') else None,
        source_label=entry.get('label') or entry.get('domain') or '',
        source_homepage=entry.get('homepage') or '',
        is_new_source=True,
        decision=Decision.ADD,
        source_metadata=json.dumps(_metadata(entry)),
    )
    apply_ai(item, _ai(entry))
    return item


# ── Decisions back ─────────────────────────────────────────────────────────────

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
    url = project.ai_callback_url
    if not url:
        raise ValueError('This project has no AI reviewer address to send the decisions to')
    _require_trusted(url, 'Sending decisions to the AI reviewer')
    response = requests.post(url, json=collect_decisions(project, project_url), headers=_headers(url),
                             timeout=REQUEST_TIMEOUT, allow_redirects=False)
    if response.status_code >= 300:
        raise RuntimeError(f'The AI reviewer answered {response.status_code}: {response.text[:300]}')
    try:
        return response.json()
    except ValueError:
        return {}
