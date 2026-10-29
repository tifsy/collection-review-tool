"""SQLAlchemy models for the review application."""
from datetime import datetime
from database import db
import enum
import json
from sqlalchemy import ForeignKey


class ReviewStatus(enum.Enum):
    """Review status enumeration."""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    COMPLETED = 'completed'


class Decision(enum.Enum):
    """Decision enumeration for review items."""
    UNDECIDED = 'undecided'
    KEEP = 'keep'
    REMOVE = 'remove'
    ADD = 'add'
    SKIP = 'skip'


class TimestampMixin:
    """Mixin for adding timestamp fields to models."""
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class ReviewProject(db.Model, TimestampMixin):
    """Manager-level container for a multi-collection review project."""
    __tablename__ = 'review_projects'

    id = db.Column(db.Integer, primary_key=True)
    guid = db.Column(db.String(36), unique=True, nullable=False, index=True)
    collection_ids_json = db.Column(db.Text, nullable=False, default='[]')
    # Human-friendly collection names corresponding to `collection_ids_json` (same order).
    collection_names_json = db.Column(db.Text, nullable=False, default='[]')

    # Status is informational; API returns derived status computed from queues.
    status = db.Column(db.String(32), nullable=True)
    name = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    guidelines_template = db.Column(db.String(100), nullable=True, default='default')
    # If set, this is the final (rendered) Markdown text used for guidelines across all reviewer queues.
    guidelines_custom_markdown = db.Column(db.Text, nullable=True)
    edit_metadata = db.Column(db.Boolean, default=False, nullable=False)
    show_virtual_queue_links_on_reviewer_landing = db.Column(db.Boolean, default=True, nullable=False)
    # MediaCloud collection id used as publish target.
    # First publish creates it; later publishes sync into the same collection.
    publish_to_collection = db.Column(db.Integer, nullable=True)
    # Projects imported from the collection AI reviewer: where the AI review came from, where the decisions
    # go back to, and the AI review itself (its new sources become items when the queues are generated).
    ai_source_url = db.Column(db.Text, nullable=True)
    ai_callback_url = db.Column(db.Text, nullable=True)
    ai_proposal_json = db.Column(db.Text, nullable=True)

    queues = db.relationship(
        'Review',
        backref='review_project',
        lazy=True,
        cascade='all, delete-orphan',
    )

    sources = db.relationship(
        'ReviewProjectSource',
        backref='review_project',
        lazy=True,
        cascade='all, delete-orphan',
    )

    def to_dict(self, include_queues=False):
        data = {
            'guid': self.guid,
            'collection_ids': json.loads(self.collection_ids_json or '[]'),
            'collection_names': json.loads(self.collection_names_json or '[]'),
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'name': self.name,
            'notes': self.notes,
            'guidelines_template': self.guidelines_template or 'default',
            'has_custom_guidelines': bool(self.guidelines_custom_markdown),
            'edit_metadata': bool(self.edit_metadata),
            'show_virtual_queue_links_on_reviewer_landing': bool(self.show_virtual_queue_links_on_reviewer_landing),
            'publish_to_collection': self.publish_to_collection,
            'is_ai_import': bool(self.ai_proposal_json),
            'ai_source_url': self.ai_source_url,
            'ai_callback_url': self.ai_callback_url,
        }
        if include_queues:
            data['queues'] = [q.to_dict(include_stats=True) for q in (self.queues or [])]
        return data


class ReviewProjectSource(db.Model, TimestampMixin):
    """A deduped seed source that belongs to a ReviewProject (before queue splitting)."""
    __tablename__ = 'review_project_sources'

    id = db.Column(db.Integer, primary_key=True)
    review_project_id = db.Column(db.Integer, ForeignKey('review_projects.id'), nullable=False, index=True)

    # MediaCloud source ID
    source_id = db.Column(db.Integer, nullable=False, index=True)
    source_label = db.Column(db.String(500), nullable=True)
    source_homepage = db.Column(db.String(1000), nullable=True)

    # JSON-encoded full source object snapshot (for later export / context)
    source_metadata = db.Column(db.Text, nullable=True)
    # The AI reviewer's call on this source (JSON), when the project was imported from an AI review
    ai_json = db.Column(db.Text, nullable=True)


class Review(db.Model, TimestampMixin):
    """Review model representing a review session for a MediaCloud collection."""
    __tablename__ = 'reviews'
    
    id = db.Column(db.Integer, primary_key=True)
    collection_id = db.Column(db.Integer, nullable=False, index=True)
    collection_name = db.Column(db.String(500), nullable=True)  # Name of the MediaCloud collection
    status = db.Column(db.Enum(ReviewStatus), default=ReviewStatus.PENDING, nullable=False)
    name = db.Column(db.String(255), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    guidelines_template = db.Column(db.String(100), nullable=True, default='default')  # Template name for annotation guidelines
    # When true, UI should allow editing of per-source language and geography metadata
    edit_metadata = db.Column(db.Boolean, default=False, nullable=False)

    # Optional linkage to a manager-level ReviewProject (when used as a reviewer queue)
    review_project_id = db.Column(db.Integer, ForeignKey('review_projects.id'), nullable=True, index=True)
    # Public GUID used for reviewer URLs (queue assignment)
    queue_guid = db.Column(db.String(36), unique=True, nullable=True, index=True)
    # Stable index within a project (0-based)
    queue_index = db.Column(db.Integer, nullable=True)
    
    # Relationship to review items
    items = db.relationship('ReviewItem', backref='review', lazy=True, cascade='all, delete-orphan')
    
    def to_dict(self, include_stats=False):
        """Convert review to dictionary."""
        data = {
            'id': self.id,
            'collection_id': self.collection_id,
            'collection_name': self.collection_name,
            'status': self.status.value,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'name': self.name,
            'notes': self.notes,
            'guidelines_template': self.guidelines_template or 'default',
            'edit_metadata': bool(self.edit_metadata),
            'review_project_id': self.review_project_id,
            'queue_guid': self.queue_guid,
            'queue_index': self.queue_index,
        }
        
        if include_stats:
            data['stats'] = self.calculate_stats()
        
        return data
    
    def calculate_stats(self):
        """Calculate statistics for this review."""
        total = len(self.items)
        keep = sum(1 for item in self.items if item.decision == Decision.KEEP)
        remove = sum(1 for item in self.items if item.decision == Decision.REMOVE)
        add = sum(1 for item in self.items if item.decision == Decision.ADD)
        undecided = sum(1 for item in self.items if item.decision == Decision.UNDECIDED)
        skip = sum(1 for item in self.items if item.decision == Decision.SKIP)
        
        return {
            'total': total,
            'keep': keep,
            'remove': remove,
            'add': add,
            'undecided': undecided,
            'skip': skip
        }


class ReviewItem(db.Model, TimestampMixin):
    """Review item model representing a source in a review."""
    __tablename__ = 'review_items'
    
    id = db.Column(db.Integer, primary_key=True)
    review_id = db.Column(db.Integer, db.ForeignKey('reviews.id'), nullable=False, index=True)
    source_id = db.Column(db.Integer, nullable=True)  # MediaCloud source ID (null for new sources)
    source_label = db.Column(db.String(500), nullable=True)
    source_homepage = db.Column(db.String(1000), nullable=True)
    is_new_source = db.Column(db.Boolean, default=False, nullable=False)
    decision = db.Column(db.Enum(Decision), default=Decision.UNDECIDED, nullable=False)
    decided_at = db.Column(db.DateTime, nullable=True)
    removal_reason = db.Column(db.Text, nullable=True)  # Reason for removal (required when decision is REMOVE)
    # Optional reviewer note when decision is SKIP (for coordinators / exports).
    skip_note = db.Column(db.Text, nullable=True)
    # Optional JSON-encoded metadata about the source as returned by MediaCloud.
    # Aligns with web-search Source model fields where present, e.g. stories_total,
    # stories_per_week, last_story, media_type, pub_country, primary_language.
    source_metadata = db.Column(db.Text, nullable=True)
    # The AI reviewer's call on this source (JSON: key, decision, proposal, decided_by, reason, note,
    # why_human, evidence). A decision prefilled from it has no decided_at; a reviewer's decision sets it.
    ai_json = db.Column(db.Text, nullable=True)

    def to_dict(self):
        """Convert review item to dictionary."""
        metadata = None
        if self.source_metadata:
            try:
                metadata = json.loads(self.source_metadata)
            except Exception:
                metadata = None
        ai = None
        if self.ai_json:
            try:
                ai = json.loads(self.ai_json)
            except Exception:
                ai = None

        return {
            'id': self.id,
            'review_id': self.review_id,
            'source_id': self.source_id,
            'source_label': self.source_label,
            'source_homepage': self.source_homepage,
            'is_new_source': self.is_new_source,
            'decision': self.decision.value,
            'decided_at': self.decided_at.isoformat() if self.decided_at else None,
            'removal_reason': self.removal_reason,
            'skip_note': self.skip_note,
            'source_metadata': metadata,
            'ai': ai,
        }
