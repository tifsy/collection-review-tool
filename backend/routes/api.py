"""API routes for the review application."""
from flask import Blueprint, request, jsonify, Response
from database import db
from models import Review, ReviewItem, ReviewStatus, Decision, ReviewProject, ReviewProjectSource
from services.mediacloud import get_mediacloud_service
from services.mediacloud_publish import MediaCloudPublishService
from services.guidelines import get_guidelines_service
from services import ai_reviewer
from config import get_config
from datetime import datetime
from urllib.parse import urlparse
import csv
import io
import os
import json
import uuid

import requests

api_bp = Blueprint('api', __name__)


def _default_publish_collection_name(project):
    project_name = (project.name or '').strip() or f'ReviewProject-{project.guid[:8]}'
    return f'{project_name} | Collection-Review'


def _build_publish_plan(project, apply_metadata_updates=False, metadata_updates_feature_enabled=True):
    queues = Review.query.filter_by(review_project_id=project.id).all()
    queue_ids = [q.id for q in queues]
    if not queue_ids:
        return {
            'rows': [],
            'summary': {
                'processed_items': 0,
                'ensure_association': 0,
                'create_source_and_associate': 0,
                'remove_association': 0,
                'metadata_updates_planned': 0,
                'metadata_updates_skipped_unchanged': 0,
                'metadata_remote_lookup_skipped': 0,
                'noop_items': 0,
            },
        }

    items = (
        ReviewItem.query.filter(ReviewItem.review_id.in_(queue_ids))
        .order_by(ReviewItem.id.asc())
        .all()
    )
    # Use service reduction logic without requiring a real token.
    reduced = {}
    for item in sorted(items, key=lambda x: x.id):
        if item.source_id is not None:
            key = f"source:{int(item.source_id)}"
        else:
            homepage = (item.source_homepage or '').strip().lower().rstrip('/')
            key = f"new:{homepage}"
        if key.endswith('new:'):
            key = f"item:{item.id}"
        reduced[key] = item

    reduced_items = list(reduced.values())
    rows = []
    summary = {
        'processed_items': len(reduced_items),
        'ensure_association': 0,
        'create_source_and_associate': 0,
        'remove_association': 0,
        'metadata_updates_planned': 0,
        'metadata_updates_skipped_unchanged': 0,
        'metadata_remote_lookup_skipped': 0,
        'noop_items': 0,
    }

    do_meta = bool(apply_metadata_updates) and bool(metadata_updates_feature_enabled)

    for item in reduced_items:
        decision = item.decision.value if item.decision else 'undecided'
        operation = 'noop'
        reason = None
        metadata_update = None
        metadata_on_create = None

        if decision in ('undecided', 'skip'):
            operation = 'noop'
            reason = f'{decision} is non-publishing state'
        elif decision in ('keep', 'add'):
            if item.source_id is None:
                operation = 'create_source_and_associate'
                summary['create_source_and_associate'] += 1
                if do_meta:
                    mc_create = MediaCloudPublishService.metadata_patch_from_item(item)
                    if mc_create:
                        metadata_on_create = dict(mc_create)
            else:
                operation = 'ensure_association'
                summary['ensure_association'] += 1
                if do_meta:
                    patch = MediaCloudPublishService.metadata_patch_from_item(item)
                    if patch:
                        metadata_update = patch
        elif decision == 'remove':
            if item.source_id is None:
                operation = 'noop'
                reason = 'new source without source_id cannot be removed from collection'
            else:
                operation = 'remove_association'
                summary['remove_association'] += 1

        if operation == 'noop':
            summary['noop_items'] += 1

        rows.append({
            'item_id': item.id,
            'source_id': item.source_id,
            'source_label': item.source_label,
            'source_homepage': item.source_homepage,
            'is_new_source': bool(item.is_new_source),
            'decision': decision,
            'operation': operation,
            'reason': reason,
            'queue_review_id': item.review_id,
            'metadata_update': metadata_update,
            'metadata_on_create': metadata_on_create,
        })

    actionable_rows = [r for r in rows if r['operation'] != 'noop']
    return {'rows': actionable_rows, 'summary': summary}


def _refine_publish_plan_metadata_with_remote(publish_service, plan):
    """
    For preview rows with planned metadata updates, compare against live DirectoryApi
    source records and shrink metadata_update to fields that actually differ.
    """
    rows = plan.get('rows') or []
    summary = plan.setdefault('summary', {})
    summary['metadata_updates_skipped_unchanged'] = 0
    summary['metadata_remote_lookup_skipped'] = 0

    for row in rows:
        desired = row.get('metadata_update')
        if not desired or not row.get('source_id'):
            continue

        record = publish_service.fetch_source_directory_record(int(row['source_id']))
        row['metadata_desired'] = dict(desired)

        if record is None:
            if publish_service.directory is None:
                row['metadata_remote_status'] = 'lookup_skipped_no_directory_api'
            else:
                row['metadata_remote_status'] = 'lookup_failed_or_source_missing'
            summary['metadata_remote_lookup_skipped'] += 1
            continue

        remote_fields = MediaCloudPublishService.metadata_fields_from_directory_record(record)
        row['metadata_current'] = {k: remote_fields.get(k, '') for k in MediaCloudPublishService.METADATA_KEYS}
        pruned = MediaCloudPublishService.prune_metadata_patch_to_changes(desired, remote_fields)
        if not pruned:
            row['metadata_update'] = None
            row['metadata_remote_status'] = 'unchanged'
            summary['metadata_updates_skipped_unchanged'] += 1
        else:
            row['metadata_update'] = pruned
            row['metadata_remote_status'] = 'changed'

    # Only count rows where we successfully compared to MediaCloud and the patch is non-empty.
    # Rows with failed lookup may still have metadata_update (full desired patch) for publish,
    # but those are counted only under metadata_remote_lookup_skipped — not here — so the
    # summary does not double-count the same sources.
    summary['metadata_updates_planned'] = sum(
        1
        for r in rows
        if r.get('metadata_remote_status') == 'changed'
        and r.get('metadata_update')
        and len(r['metadata_update']) > 0
    )


def _country_collections_path():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(backend_dir, 'data', 'country-collections.json')


@api_bp.route('/meta/country-collections', methods=['GET'])
def get_country_collections():
    """
    Vendored MediaCloud geographic collections (same source as web-search
    mcweb/backend/sources/data/country-collections.json).
    Served via /api so split deployments use the same origin and CORS as other API calls.
    """
    path = _country_collections_path()
    if not os.path.isfile(path):
        return jsonify({'error': 'Country collections data is not installed on the server'}), 404
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return jsonify(data), 200
    except Exception as e:
        return jsonify({'error': f'Failed to read country collections: {str(e)}'}), 500


@api_bp.route('/guidelines/templates', methods=['GET'])
def get_guideline_templates():
    """Get list of available guideline templates."""
    try:
        service = get_guidelines_service()
        templates = service.get_available_templates()
        return jsonify({'templates': templates}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch templates: {str(e)}'}), 500


@api_bp.route('/reviews/<int:review_id>/guidelines', methods=['GET'])
def get_review_guidelines(review_id):
    """Get rendered guidelines for a review."""
    try:
        review = Review.query.get_or_404(review_id)
        service = get_guidelines_service()
        template_name = review.guidelines_template or 'default'
        guidelines = service.render_guidelines(template_name, review)
        return jsonify({'guidelines': guidelines}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch guidelines: {str(e)}'}), 500


@api_bp.route('/reviews/start', methods=['POST'])
def start_review():
    """
    Start or resume a review for a MediaCloud collection.
    
    POST /api/reviews/start
    Body: { "collection_id": 123 }
    
    Returns: Review JSON with stats
    """
    try:
        data = request.get_json()
        if not data or 'collection_id' not in data:
            return jsonify({'error': 'collection_id is required'}), 400
        
        collection_id = data['collection_id']
        guidelines_template = data.get('guidelines_template', 'default')
        edit_metadata = bool(data.get('edit_metadata', False))
        
        # Check for existing active review (status != 'completed')
        existing_review = Review.query.filter_by(
            collection_id=collection_id
        ).filter(
            Review.status != ReviewStatus.COMPLETED
        ).filter(
            Review.review_project_id.is_(None)
        ).first()
        
        if existing_review:
            # If collection_name or name is not set, try to fetch them from MediaCloud
            if not existing_review.collection_name or not existing_review.name:
                try:
                    mediacloud = get_mediacloud_service()
                    collection_details = mediacloud.fetch_collection_details(collection_id)
                    collection_name = collection_details.get('name', f'Collection {collection_id}')
                    if not existing_review.collection_name:
                        existing_review.collection_name = collection_name
                    if not existing_review.name:
                        existing_review.name = collection_name
                    db.session.commit()
                except Exception:
                    # If fetching fails, ensure we at least have sensible defaults
                    existing_review.collection_name = existing_review.collection_name or f'Collection {collection_id}'
                    existing_review.name = existing_review.name or existing_review.collection_name
            
            # Optionally update edit_metadata if provided
            if 'edit_metadata' in data:
                existing_review.edit_metadata = edit_metadata
                db.session.commit()
            
            # Return existing review with stats
            return jsonify({
                'review': existing_review.to_dict(include_stats=True)
            }), 200
        
        # Fetch collection details and sources from MediaCloud
        mediacloud = get_mediacloud_service()
        
        # Fetch collection name
        try:
            collection_details = mediacloud.fetch_collection_details(collection_id)
            collection_name = collection_details.get('name', f'Collection {collection_id}')
        except Exception as e:
            # If fetching collection name fails, use default
            collection_name = f'Collection {collection_id}'
        
        # Create new review, using the collection name as the human-friendly review name
        new_review = Review(
            collection_id=collection_id,
            collection_name=collection_name,
            name=collection_name,
            status=ReviewStatus.IN_PROGRESS,
            guidelines_template=guidelines_template,
            edit_metadata=edit_metadata
        )
        db.session.add(new_review)
        db.session.flush()  # Get the review ID
        
        # Fetch sources from MediaCloud
        try:
            sources = mediacloud.fetch_collection_sources(collection_id)
        except Exception as e:
            # Rollback review creation
            db.session.rollback()
            return jsonify({
                'error': f'Failed to fetch sources from MediaCloud: {str(e)}'
            }), 502
        
        # Create ReviewItems from sources, capturing full source metadata for later use
        for source in sources:
            review_item = ReviewItem(
                review_id=new_review.id,
                source_id=source['id'],
                source_label=source.get('label', ''),
                source_homepage=source.get('homepage', ''),
                is_new_source=False,
                decision=Decision.UNDECIDED,
                source_metadata=json.dumps(source)
            )
            db.session.add(review_item)
        
        # Commit all changes
        db.session.commit()
        
        # Return new review with stats
        return jsonify({
            'review': new_review.to_dict(include_stats=True)
        }), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@api_bp.route('/review-projects/start', methods=['POST'])
def start_review_project():
    """
    Start a ReviewProject from multiple MediaCloud collections.

    POST /api/review-projects/start
    Body: {
      "collection_ids": [123, 456],
      "queue_count": 3,
      "guidelines_template": "default",
      "edit_metadata": false,
      "name": "Optional project name"
    }
    """
    try:
        data = request.get_json() or {}
        collection_ids = data.get('collection_ids') or []
        _queue_count = data.get('queue_count')  # optional; ignored in step 1
        guidelines_template = data.get('guidelines_template', 'default')
        edit_metadata = bool(data.get('edit_metadata', False))
        show_virtual_queue_links_on_reviewer_landing = bool(
            data.get('show_virtual_queue_links_on_reviewer_landing', True)
        )
        project_name = data.get('name') or None

        if not isinstance(collection_ids, list) or len(collection_ids) == 0:
            return jsonify({'error': 'collection_ids must be a non-empty array'}), 400
        try:
            collection_ids = [int(cid) for cid in collection_ids]
        except Exception:
            return jsonify({'error': 'collection_ids must contain integers'}), 400

        # Fetch and dedupe sources across all input collections.
        # Also fetch collection names for display on the manager pages.
        mediacloud = get_mediacloud_service()
        ordered_deduped_sources = []
        sources_by_id = {}
        ordered_collection_names = []

        for collection_id in collection_ids:
            # Best-effort: collection_details is used purely for nicer metadata.
            try:
                details = mediacloud.fetch_collection_details(collection_id)
                ordered_collection_names.append(details.get('name') or f'Collection {collection_id}')
            except Exception:
                ordered_collection_names.append(f'Collection {collection_id}')

            sources = mediacloud.fetch_collection_sources(collection_id)
            for source in sources:
                raw_source_id = source.get('id') or source.get('media_id') or source.get('source_id')
                if raw_source_id is None:
                    continue
                source_id = int(raw_source_id)

                if source_id not in sources_by_id:
                    # Ensure the dict has an integer `id` key.
                    source = dict(source)
                    source['id'] = source_id
                    sources_by_id[source_id] = source
                    ordered_deduped_sources.append(source)

        deduped_source_count = len(ordered_deduped_sources)
        if deduped_source_count == 0:
            return jsonify({'error': 'No sources found across provided collections'}), 400

        project_guid = str(uuid.uuid4())
        final_project_name = project_name or f'ReviewProject ({len(collection_ids)} collections)'

        project = ReviewProject(
            guid=project_guid,
            collection_ids_json=json.dumps(collection_ids),
            collection_names_json=json.dumps(ordered_collection_names),
            status=None,
            name=final_project_name,
            notes=data.get('notes'),
            guidelines_template=guidelines_template,
            edit_metadata=edit_metadata,
            show_virtual_queue_links_on_reviewer_landing=show_virtual_queue_links_on_reviewer_landing,
        )
        db.session.add(project)
        db.session.flush()

        # Store the deduped source set at the project level. Reviewer queues are generated in step 2.
        for source in ordered_deduped_sources:
            item = ReviewProjectSource(
                review_project_id=project.id,
                source_id=int(source.get('id')),
                source_label=source.get('label', '') or '',
                source_homepage=source.get('homepage', '') or '',
                source_metadata=json.dumps(source),
            )
            db.session.add(item)

        db.session.commit()

        warning = None
        if _queue_count is not None:
            warning = 'Queues were not generated yet. Enter `queue_count` on the project page to split into reviewer queues.'

        stats = {
            'total': deduped_source_count,
            'keep': 0,
            'remove': 0,
            'add': 0,
            'undecided': deduped_source_count,
            'skip': 0,
        }

        return jsonify({
            'project': project.to_dict(),
            'derived_status': 'pending',
            'queues': [],
            'stats': stats,
            'collections_count': len(collection_ids),
            'sources_total': deduped_source_count,
            'warning': warning,
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>', methods=['GET'])
def get_review_project(project_guid):
    """
    Get a ReviewProject with per-queue summaries.
    Project status is derived (compute-on-read) from queue exhaustion.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        collection_ids = json.loads(project.collection_ids_json or '[]')
        collections_count = len(collection_ids)

        sources_total = ReviewProjectSource.query.filter_by(review_project_id=project.id).count()

        queues = Review.query.filter_by(review_project_id=project.id).order_by(Review.queue_index.asc()).all()

        base_stats = {
            'total': sources_total,
            'keep': 0,
            'remove': 0,
            'add': 0,
            'undecided': sources_total,
            'skip': 0,
        }

        if not queues:
            derived_status = 'pending'
            queue_dicts = []
            stats = base_stats
        else:
            # Derived completion is based on queue exhaustion (no undecided items).
            queue_completion = []
            totals = {
                'total': 0,
                'keep': 0,
                'remove': 0,
                'add': 0,
                'undecided': 0,
                'skip': 0,
            }

            queue_dicts = []
            for q in queues:
                undecided_count = ReviewItem.query.filter_by(review_id=q.id, decision=Decision.UNDECIDED).count()
                derived_queue_status = 'completed' if undecided_count == 0 else 'in_progress'
                queue_completion.append(undecided_count == 0)

                q_data = q.to_dict(include_stats=True)
                q_data['status'] = derived_queue_status
                q_data['undecided_count'] = undecided_count
                queue_dicts.append(q_data)

                if q_data.get('stats'):
                    for key in totals.keys():
                        totals[key] += q_data['stats'].get(key, 0)

            derived_status = 'completed' if all(queue_completion) else 'in_progress'
            stats = totals

        return jsonify({
            'project': project.to_dict(),
            'derived_status': derived_status,
            'queues': queue_dicts,
            'stats': stats,
            'collections_count': collections_count,
            'sources_total': sources_total,
            'publish_enabled': bool(get_config().MEDIACLOUD_PUBLISH_ENABLED),
            'publish_metadata_updates_enabled': bool(get_config().MEDIACLOUD_PUBLISH_METADATA_UPDATES_ENABLED),
            'publish_target_api_base_url': (
                (get_config().MEDIACLOUD_UPLOAD_BASE_URL or '').strip() or 'https://search.mediacloud.org/api/'
            ),
        }), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch review project: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/publish/preview', methods=['POST'])
def preview_publish_review_project(project_guid):
    """
    Build a publish preview plan and run token preflight.
    """
    try:
        if not bool(get_config().MEDIACLOUD_PUBLISH_ENABLED):
            return jsonify({'error': 'Direct MediaCloud publish is disabled by server configuration'}), 403

        data = request.get_json() or {}
        api_token = (data.get('api_token') or '').strip()
        if not api_token:
            return jsonify({'error': 'api_token is required'}), 400

        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        publish_service = MediaCloudPublishService(api_token=api_token)

        preflight = publish_service.preflight()
        cfg = get_config()
        apply_metadata = bool(data.get('apply_metadata_updates_to_existing_sources'))
        plan = _build_publish_plan(
            project,
            apply_metadata_updates=apply_metadata,
            metadata_updates_feature_enabled=bool(cfg.MEDIACLOUD_PUBLISH_METADATA_UPDATES_ENABLED),
        )
        if (
            apply_metadata
            and bool(cfg.MEDIACLOUD_PUBLISH_METADATA_UPDATES_ENABLED)
            and (plan.get('rows') or [])
        ):
            _refine_publish_plan_metadata_with_remote(publish_service, plan)
        default_collection_name = _default_publish_collection_name(project)

        return jsonify({
            'preflight': preflight,
            'target': {
                'is_existing_collection': project.publish_to_collection is not None,
                'collection_id': project.publish_to_collection,
                'collection_name': (
                    (data.get('collection_name') or '').strip() or default_collection_name
                ),
            },
            'preview': plan,
            'apply_metadata_updates_to_existing_sources': apply_metadata,
            'metadata_updates_feature_enabled': bool(cfg.MEDIACLOUD_PUBLISH_METADATA_UPDATES_ENABLED),
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to preview publish: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/publish', methods=['POST'])
def publish_review_project(project_guid):
    """
    Publish ReviewProject decisions directly into MediaCloud.

    - First publish creates a new collection and stores its id on the project.
    - Later publishes sync into the same collection.
    - KEEP/ADD ensure source is associated with collection.
    - REMOVE removes source association from collection (does not delete source globally).
    - SKIP/UNDECIDED are no-op.
    """
    try:
        if not bool(get_config().MEDIACLOUD_PUBLISH_ENABLED):
            return jsonify({'error': 'Direct MediaCloud publish is disabled by server configuration'}), 403

        data = request.get_json() or {}
        api_token = (data.get('api_token') or '').strip()
        if not api_token:
            return jsonify({'error': 'api_token is required'}), 400

        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        publish_service = MediaCloudPublishService(api_token=api_token)
        cfg = get_config()
        apply_metadata = (
            bool(data.get('apply_metadata_updates_to_existing_sources'))
            and bool(cfg.MEDIACLOUD_PUBLISH_METADATA_UPDATES_ENABLED)
        )

        created_collection = False
        collection_name = (data.get('collection_name') or '').strip() or _default_publish_collection_name(project)

        if project.publish_to_collection is None:
            collection_id, _created_payload = publish_service.create_collection(collection_name)
            project.publish_to_collection = int(collection_id)
            created_collection = True
        else:
            collection_id = int(project.publish_to_collection)

        queues = Review.query.filter_by(review_project_id=project.id).all()
        queue_ids = [q.id for q in queues]
        if not queue_ids:
            db.session.commit()
            return jsonify({
                'created_collection': created_collection,
                'collection_id': collection_id,
                'collection_name': collection_name,
                'summary': {
                    'processed_items': 0,
                    'ensured_associations': 0,
                    'removed_associations': 0,
                    'created_sources': 0,
                    'metadata_updates_attempted': 0,
                    'metadata_updates_succeeded': 0,
                    'metadata_updates_failed': 0,
                    'noop_items': 0,
                    'errors': [],
                    'warnings': [],
                }
            }), 200

        items = (
            ReviewItem.query.filter(ReviewItem.review_id.in_(queue_ids))
            .order_by(ReviewItem.id.asc())
            .all()
        )
        reduced_items = publish_service.reduce_items_for_publish(items)

        seen_associations = set()
        seen_removals = set()
        ensured_associations = 0
        removed_associations = 0
        created_sources = 0
        metadata_updates_attempted = 0
        metadata_updates_succeeded = 0
        metadata_updates_failed = 0
        noop_items = 0
        errors = []
        warnings = []

        for item in reduced_items:
            decision = item.decision
            if decision in (Decision.UNDECIDED, Decision.SKIP):
                noop_items += 1
                continue

            try:
                original_source_id = item.source_id
                source_id = item.source_id
                if source_id is None and decision in (Decision.KEEP, Decision.ADD):
                    source_id, _created = publish_service.create_source(item)
                    created_sources += 1

                if source_id is None:
                    warnings.append(f'Item {item.id} has no source id and was skipped.')
                    noop_items += 1
                    continue

                source_id = int(source_id)

                if decision in (Decision.KEEP, Decision.ADD):
                    if apply_metadata and original_source_id is not None:
                        patch, _remote, dir_record = publish_service.metadata_patch_needed_for_source(item)
                        if patch:
                            metadata_updates_attempted += 1
                            try:
                                publish_service.update_source_metadata(
                                    source_id, item, patch, directory_record=dir_record
                                )
                                metadata_updates_succeeded += 1
                            except Exception as meta_err:
                                metadata_updates_failed += 1
                                message = MediaCloudPublishService.describe_client_exception(meta_err)
                                lower = message.lower()
                                if (
                                    'already' in lower
                                    or 'exists' in lower
                                    or 'not found' in lower
                                    or 'does not exist' in lower
                                ):
                                    warnings.append(f'Item {item.id} metadata update: {message}')
                                else:
                                    errors.append(f'Item {item.id} metadata update: {message}')
                    key = (source_id, collection_id)
                    if key not in seen_associations:
                        publish_service.ensure_source_in_collection(source_id, collection_id)
                        seen_associations.add(key)
                        ensured_associations += 1
                elif decision == Decision.REMOVE:
                    key = (source_id, collection_id)
                    if key not in seen_removals:
                        publish_service.remove_source_from_collection(source_id, collection_id)
                        seen_removals.add(key)
                        removed_associations += 1
                else:
                    noop_items += 1

            except Exception as item_error:
                message = MediaCloudPublishService.describe_client_exception(item_error)
                lower = message.lower()
                # Keep republish behavior resilient: duplicates/missing links are no-op warnings.
                if (
                    'already' in lower
                    or 'exists' in lower
                    or 'not found' in lower
                    or 'does not exist' in lower
                ):
                    warnings.append(f'Item {item.id}: {message}')
                else:
                    errors.append(f'Item {item.id}: {message}')

        if not created_collection:
            try:
                publish_service.append_update_note(collection_id)
            except Exception as note_error:
                warnings.append(
                    f'Collection note update failed: {MediaCloudPublishService.describe_client_exception(note_error)}'
                )

        db.session.commit()
        return jsonify({
            'created_collection': created_collection,
            'collection_id': collection_id,
            'collection_name': collection_name,
            'summary': {
                'processed_items': len(reduced_items),
                'ensured_associations': ensured_associations,
                'removed_associations': removed_associations,
                'created_sources': created_sources,
                'metadata_updates_attempted': metadata_updates_attempted,
                'metadata_updates_succeeded': metadata_updates_succeeded,
                'metadata_updates_failed': metadata_updates_failed,
                'noop_items': noop_items,
                'errors': errors,
                'warnings': warnings,
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to publish review project: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/edit-metadata', methods=['PATCH'])
def set_review_project_edit_metadata(project_guid):
    """
    Toggle whether reviewers can edit per-source metadata in reviewer queues.

    This propagates down to all existing reviewer queues for the project.
    """
    try:
        data = request.get_json() or {}
        if 'edit_metadata' not in data:
            return jsonify({'error': 'edit_metadata is required'}), 400

        edit_metadata = bool(data.get('edit_metadata'))

        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        project.edit_metadata = edit_metadata

        queues = Review.query.filter_by(review_project_id=project.id).all()
        for q in queues:
            q.edit_metadata = edit_metadata

        db.session.commit()

        return jsonify({
            'project': project.to_dict(),
            'queues_updated': len(queues),
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update review project edit_metadata: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/reviewer-landing-virtual-queues', methods=['PATCH'])
def set_review_project_reviewer_landing_virtual_queues(project_guid):
    """
    Toggle whether reviewer landing pages show project virtual queue links.
    """
    try:
        data = request.get_json() or {}
        if 'show_virtual_queue_links_on_reviewer_landing' not in data:
            return jsonify({'error': 'show_virtual_queue_links_on_reviewer_landing is required'}), 400

        show_links = bool(data.get('show_virtual_queue_links_on_reviewer_landing'))

        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        project.show_virtual_queue_links_on_reviewer_landing = show_links
        db.session.commit()

        return jsonify({'project': project.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'error': f'Failed to update reviewer landing virtual queue visibility: {str(e)}'
        }), 500


@api_bp.route('/review-projects/<string:project_guid>/name', methods=['PATCH'])
def set_review_project_name(project_guid):
    """
    Update a ReviewProject's display name.
    """
    try:
        data = request.get_json() or {}
        raw_name = data.get('name')
        if raw_name is None:
            return jsonify({'error': 'name is required'}), 400

        name = str(raw_name).strip()
        if not name:
            return jsonify({'error': 'name cannot be empty'}), 400
        if len(name) > 255:
            return jsonify({'error': 'name must be 255 characters or fewer'}), 400

        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        project.name = name

        db.session.commit()
        return jsonify({'project': project.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update review project name: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/guidelines', methods=['GET'])
def get_review_project_guidelines(project_guid):
    """
    Get the final guidelines Markdown for a project.
    - If the project has been customized, return stored final Markdown.
    - Otherwise, render the selected template using stable project-level context.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        service = get_guidelines_service()

        if project.guidelines_custom_markdown:
            return jsonify({'guidelines': project.guidelines_custom_markdown}), 200

        template_name = project.guidelines_template or 'default'

        primary_collection_id = None
        if project.collection_ids_json:
            try:
                ids = json.loads(project.collection_ids_json or '[]')
                primary_collection_id = ids[0] if ids else None
            except Exception:
                primary_collection_id = None

        context_overrides = {
            'collection_name': project.name if project.name else 'ReviewProject',
            'collection_id': primary_collection_id,
            'review_id': project.id,
            'review_name': project.name if project.name else 'ReviewProject',
        }

        # Render with a queue-like context surface; GuidelinesService supports ReviewProject via getattr fallbacks.
        guidelines = service.render_guidelines(template_name, project, context_overrides=context_overrides)
        return jsonify({'guidelines': guidelines}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch review project guidelines: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/guidelines', methods=['PATCH'])
def set_review_project_guidelines(project_guid):
    """
    Store final (rendered) guidelines Markdown for the project.
    This is returned verbatim by reviewer queue pages.
    """
    try:
        data = request.get_json() or {}
        raw_markdown = data.get('guidelines')
        if raw_markdown is None:
            return jsonify({'error': 'guidelines is required'}), 400

        markdown = str(raw_markdown)
        if not markdown.strip():
            return jsonify({'error': 'guidelines cannot be empty'}), 400

        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        project.guidelines_custom_markdown = markdown
        db.session.commit()
        return jsonify({'project': project.to_dict()}), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update review project guidelines: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/queues', methods=['POST'])
def generate_review_project_queues(project_guid):
    """
    Step 2: generate reviewer queues for a ReviewProject.

    POST /api/review-projects/<project_guid>/queues
    Body: { "queue_count": 3 }
    """
    try:
        data = request.get_json() or {}
        queue_count = data.get('queue_count')
        try:
            queue_count = int(queue_count)
        except Exception:
            return jsonify({'error': 'queue_count is required and must be an integer'}), 400

        if queue_count <= 0:
            return jsonify({'error': 'queue_count must be a positive integer'}), 400

        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        collection_ids = json.loads(project.collection_ids_json or '[]')
        # An AI review of a proposed collection (not in Media Cloud yet) has no collection id
        if not collection_ids and not project.ai_proposal_json:
            return jsonify({'error': 'ReviewProject is missing collection_ids'}), 400
        primary_collection_id = collection_ids[0] if collection_ids else 0

        existing_queues_count = Review.query.filter_by(review_project_id=project.id).count()
        if existing_queues_count > 0:
            return jsonify({'error': 'Reviewer queues were already generated for this project'}), 400

        sources = ReviewProjectSource.query.filter_by(review_project_id=project.id).order_by(ReviewProjectSource.id.asc()).all()
        sources = ai_reviewer.order_for_queues(sources)
        new_sources_total = ai_reviewer.new_source_count(project)
        sources_total = len(sources) + new_sources_total
        if sources_total == 0:
            return jsonify({'error': 'No sources found for this project; cannot generate queues'}), 400

        effective_queue_count = min(queue_count, sources_total)
        warning = None
        if effective_queue_count < queue_count:
            warning = (
                f'Requested queue_count={queue_count}, but only {sources_total} '
                f'unique sources exist. Creating {effective_queue_count} queues.'
            )

        # Partition sources into disjoint buckets.
        queue_buckets = [[] for _ in range(effective_queue_count)]
        for i, source in enumerate(sources):
            queue_buckets[i % effective_queue_count].append(source)

        created_queues = []
        for queue_index in range(effective_queue_count):
            queue_guid = str(uuid.uuid4())
            queue_name = f'{project.name} - Queue {queue_index + 1}'

            queue_review = Review(
                collection_id=primary_collection_id,
                collection_name=queue_name,
                status=ReviewStatus.IN_PROGRESS,
                name=queue_name,
                notes=None,
                guidelines_template=project.guidelines_template,
                edit_metadata=project.edit_metadata,
                review_project_id=project.id,
                queue_guid=queue_guid,
                queue_index=queue_index,
            )
            db.session.add(queue_review)
            db.session.flush()

            for source in queue_buckets[queue_index]:
                item = ReviewItem(
                    review_id=queue_review.id,
                    source_id=source.source_id,
                    source_label=source.source_label or '',
                    source_homepage=source.source_homepage or '',
                    is_new_source=False,
                    decision=Decision.UNDECIDED,
                    source_metadata=source.source_metadata,
                )
                if source.ai_json:
                    ai_reviewer.apply_ai(item, json.loads(source.ai_json))
                db.session.add(item)

            created_queues.append(queue_review)

        if new_sources_total:
            # the AI's additions, continuing the round-robin where the seed sources left off
            ai_reviewer.add_new_source_items(project, created_queues, start=len(sources) % effective_queue_count)

        db.session.commit()

        return jsonify({
            'queues': [q.to_dict(include_stats=True) for q in created_queues],
            'warning': warning,
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to generate queues: {str(e)}'}), 500


@api_bp.route('/review-projects/import-ai', methods=['POST'])
def import_ai_review():
    """
    Start a ReviewProject from the AI reviewer's AI-enhanced collection (schema mediacloud-ai-review/1).
    The AI's clear calls arrive filled in; what it left for people arrives undecided. Generate the reviewer
    queues afterwards as for any project (POST /api/review-projects/<guid>/queues).

    POST /api/review-projects/import-ai
    Body: { "url": "<ai reviewer>/api/collections/<key>/proposal.json" }  or  { "proposal": {...} },
          optional "name", "edit_metadata"
    """
    data = request.get_json() or {}
    try:
        if data.get('proposal'):
            proposal = data['proposal']
        elif data.get('url'):
            proposal = ai_reviewer.fetch_proposal(data['url'])
        else:
            return jsonify({'error': 'Give the AI review as "url" or "proposal"'}), 400
        project, existing, new = ai_reviewer.create_project(
            proposal, source_url=data.get('url'), name=data.get('name'), edit_metadata=data.get('edit_metadata', False)
        )
        db.session.commit()
    except (ValueError, requests.RequestException) as e:
        db.session.rollback()
        return jsonify({'error': f'Could not import the AI review: {e}'}), 400
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to import the AI review: {str(e)}'}), 500
    return jsonify({
        'project': project.to_dict(),
        'existing_sources': existing,
        'new_sources': new,
        'summary': proposal.get('summary'),
    }), 201


@api_bp.route('/review-projects/<string:project_guid>/ai-decisions', methods=['GET'])
def get_ai_decisions(project_guid):
    """Every item's current decision, in the AI reviewer's format (schema mediacloud-ai-review-decisions/1)."""
    project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
    return jsonify(ai_reviewer.collect_decisions(project, f"{request.host_url.rstrip('/')}/review-projects/{project.guid}"))


@api_bp.route('/review-projects/<string:project_guid>/ai-decisions/send', methods=['POST'])
def send_ai_decisions(project_guid):
    """Send the decisions back to the AI reviewer, which rebuilds the collection's final package."""
    project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
    try:
        result = ai_reviewer.send_decisions(project, f"{request.host_url.rstrip('/')}/review-projects/{project.guid}")
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except (RuntimeError, requests.RequestException) as e:
        return jsonify({'error': f'Could not send the decisions: {e}'}), 502
    return jsonify(result), 200


@api_bp.route('/review-projects', methods=['GET'])
def get_review_projects():
    """
    List all ReviewProjects with derived status and aggregated queue stats.
    """
    try:
        projects = ReviewProject.query.order_by(ReviewProject.created_at.desc()).all()
        result = []

        for project in projects:
            collection_ids = json.loads(project.collection_ids_json or '[]')
            collections_count = len(collection_ids)

            sources_total = ReviewProjectSource.query.filter_by(review_project_id=project.id).count()
            queues = Review.query.filter_by(review_project_id=project.id).order_by(Review.queue_index.asc()).all()
            queues_count = len(queues)

            if queues_count == 0:
                derived_status = 'pending'
                totals = {
                    'total': sources_total,
                    'keep': 0,
                    'remove': 0,
                    'add': 0,
                    'undecided': sources_total,
                    'skip': 0,
                }
            else:
                # Aggregate stats across queues
                totals = {
                    'total': 0,
                    'keep': 0,
                    'remove': 0,
                    'add': 0,
                    'undecided': 0,
                    'skip': 0,
                }

                queue_statuses = []
                for q in queues:
                    q_total = ReviewItem.query.filter_by(review_id=q.id).count()
                    q_keep = ReviewItem.query.filter_by(review_id=q.id, decision=Decision.KEEP).count()
                    q_remove = ReviewItem.query.filter_by(review_id=q.id, decision=Decision.REMOVE).count()
                    q_add = ReviewItem.query.filter_by(review_id=q.id, decision=Decision.ADD).count()
                    q_undecided = ReviewItem.query.filter_by(review_id=q.id, decision=Decision.UNDECIDED).count()
                    q_skip = ReviewItem.query.filter_by(review_id=q.id, decision=Decision.SKIP).count()

                    totals['total'] += q_total
                    totals['keep'] += q_keep
                    totals['remove'] += q_remove
                    totals['add'] += q_add
                    totals['undecided'] += q_undecided
                    totals['skip'] += q_skip

                    queue_statuses.append(q_undecided == 0)

                derived_status = 'completed' if all(queue_statuses) else 'in_progress'

            result.append({
                'guid': project.guid,
                'name': project.name,
                'collection_ids': collection_ids,
                'collections_count': collections_count,
                'derived_status': derived_status,
                'created_at': project.created_at.isoformat() if project.created_at else None,
                'updated_at': project.updated_at.isoformat() if project.updated_at else None,
                'stats': totals,
                'queues_count': queues_count,
            })

        return jsonify({'projects': result}), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch review projects: {str(e)}'}), 500


_SKIP_NOTE_MAX_LEN = 4000


def _effective_queue_edit_metadata(queue_review):
    """Queue-level metadata edit setting aliases to the parent project when present."""
    if queue_review.review_project is not None:
        return bool(queue_review.review_project.edit_metadata)
    return bool(queue_review.edit_metadata)


def _apply_review_item_decision_fields(item, decision_enum, data):
    """
    Set removal_reason and skip_note from JSON body for the chosen decision.
    Returns an error message string if validation fails, otherwise None.
    """
    if decision_enum == Decision.REMOVE:
        removal_reason = (data.get('removal_reason') or '').strip()
        if not removal_reason:
            return 'removal_reason is required when decision is "remove"'
        item.removal_reason = removal_reason
        item.skip_note = None
    elif decision_enum == Decision.SKIP:
        item.removal_reason = None
        raw = data.get('skip_note')
        note = '' if raw is None else str(raw).strip()
        item.skip_note = (note[:_SKIP_NOTE_MAX_LEN] if note else None)
    else:
        item.removal_reason = None
        item.skip_note = None
    return None


def _extract_domain_from_homepage(homepage):
    if not homepage:
        return ''
    try:
        return urlparse(homepage).netloc or ''
    except Exception:
        return ''


def _load_mc_csv_column_names():
    """Column names for Media Cloud-style source CSV exports (matches mc_csv_columns.txt)."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    columns_file = os.path.join(base_dir, '..', 'mc_csv_columns.txt')
    try:
        with open(columns_file, 'r') as f:
            return [line.strip().split('\t')[0].strip() for line in f if line.strip()]
    except FileNotFoundError:
        return [
            'id', 'homepage', 'domain', 'url_search_string', 'label', 'notes',
            'platform', 'pub_country', 'pub_state', 'media_type',
            'stories_total', 'stories_per_week', 'last_story', 'primary_language'
        ]


def _review_project_item_mc_row_values(item, mc_columns):
    """Build one CSV row (list of strings) for a ReviewItem in Media Cloud column order (any decision)."""
    row = {}
    # A new source imported from the AI reviewer carries its metadata (and its directory id, when it has one):
    # export it through the metadata branch below.
    if item.is_new_source and not item.ai_json:
        homepage = item.source_homepage or ''
        domain = _extract_domain_from_homepage(homepage)
        label = item.source_label or ''
        for col in mc_columns:
            if col == 'id':
                row[col] = ''
            elif col == 'homepage':
                row[col] = homepage
            elif col == 'domain':
                row[col] = domain
            elif col == 'label':
                row[col] = label
            else:
                row[col] = ''
    else:
        metadata = {}
        if item.source_metadata:
            try:
                metadata = json.loads(item.source_metadata) or {}
            except Exception:
                metadata = {}

        homepage = (
            metadata.get('url')
            or metadata.get('homepage')
            or metadata.get('media_url')
            or item.source_homepage
            or ''
        )
        domain = metadata.get('domain') or _extract_domain_from_homepage(homepage)
        label = (
            metadata.get('name')
            or metadata.get('label')
            or item.source_label
            or ''
        )
        source_id_val = metadata.get('id') or item.source_id or ''

        for col in mc_columns:
            if col == 'id':
                row[col] = source_id_val
            elif col == 'homepage':
                row[col] = homepage
            elif col == 'domain':
                row[col] = domain
            elif col == 'label':
                row[col] = label
            elif col == 'primary_language':
                row[col] = metadata.get('primary_language') or metadata.get('language') or ''
            else:
                row[col] = metadata.get(col, '') or ''

    return [row.get(col, '') for col in mc_columns]


@api_bp.route('/review-projects/<string:project_guid>/export', methods=['GET'])
def export_review_project(project_guid):
    """
    Export a ReviewProject as a single aggregated CSV for Media Cloud collection workflows.

    Includes only KEEP and ADD rows (sources to retain in the collection). Skip, remove, and
    undecided sources are omitted. Use /export/audit for every row with decision labels.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        queues = Review.query.filter_by(review_project_id=project.id).all()

        queue_ids = [q.id for q in queues]
        items = []
        if queue_ids:
            items = ReviewItem.query.filter(
                ReviewItem.review_id.in_(queue_ids)
            ).filter(
                ReviewItem.decision.in_([Decision.KEEP, Decision.ADD])
            ).all()

        mc_columns = _load_mc_csv_column_names()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(mc_columns)

        for item in items:
            writer.writerow(_review_project_item_mc_row_values(item, mc_columns))

        output.seek(0)
        csv_content = output.getvalue()

        response = Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=review_project_{project_guid}_export.csv'
            }
        )
        return response

    except Exception as e:
        return jsonify({'error': f'Failed to export review project: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/export/audit', methods=['GET'])
def export_review_project_audit(project_guid):
    """
    Full-project CSV: Media Cloud source columns plus review_decision, removal_reason,
    skip_note, and reviewer_queue (1-based queue index) for every item in all reviewer queues.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        queues = Review.query.filter_by(review_project_id=project.id).order_by(Review.queue_index.asc()).all()
        queue_ids = [q.id for q in queues]
        queue_by_review_id = {q.id: q for q in queues}

        mc_columns = _load_mc_csv_column_names()
        extra = ['review_decision', 'removal_reason', 'skip_note', 'reviewer_queue',
                 'ai_decision', 'ai_decided_by', 'ai_reason', 'decided_at']

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(mc_columns + extra)

        if not queue_ids:
            output.seek(0)
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={
                    'Content-Disposition': f'attachment; filename=review_project_{project_guid}_audit.csv'
                },
            )

        items = (
            ReviewItem.query.filter(ReviewItem.review_id.in_(queue_ids))
            .order_by(ReviewItem.review_id.asc(), ReviewItem.id.asc())
            .all()
        )
        items.sort(
            key=lambda it: (
                queue_by_review_id[it.review_id].queue_index
                if queue_by_review_id.get(it.review_id) and queue_by_review_id[it.review_id].queue_index is not None
                else 0,
                it.id,
            )
        )

        for item in items:
            base = _review_project_item_mc_row_values(item, mc_columns)
            q = queue_by_review_id.get(item.review_id)
            qn = ''
            if q is not None and q.queue_index is not None:
                qn = (q.queue_index or 0) + 1
            ai = json.loads(item.ai_json) if item.ai_json else {}
            writer.writerow(
                base
                + [
                    item.decision.value if item.decision else '',
                    item.removal_reason or '',
                    item.skip_note or '',
                    qn,
                    ai.get('decision', ''),
                    ai.get('decided_by', ''),
                    ai.get('reason', ''),
                    item.decided_at.isoformat() if item.decided_at else '',
                ]
            )

        output.seek(0)
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=review_project_{project_guid}_audit.csv'
            },
        )

    except Exception as e:
        return jsonify({'error': f'Failed to export audit CSV: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/all-queue-items', methods=['GET'])
def get_all_queue_items_for_project(project_guid):
    """
    All ReviewItem rows across reviewer queues for this project (for UI preview / summaries).

    Ordered by queue index then item id. Paginated; default page_size 500, max 8000.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 500, type=int)
        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 500
        page_size = min(page_size, 8000)

        queues = Review.query.filter_by(review_project_id=project.id).order_by(Review.queue_index.asc()).all()
        queue_ids = [q.id for q in queues]
        queue_by_review_id = {q.id: q for q in queues}

        if not queue_ids:
            return jsonify({'items': [], 'total': 0, 'page': page, 'page_size': page_size}), 200

        all_items = (
            ReviewItem.query.filter(ReviewItem.review_id.in_(queue_ids))
            .order_by(ReviewItem.id.asc())
            .all()
        )
        all_items.sort(
            key=lambda it: (
                queue_by_review_id[it.review_id].queue_index
                if queue_by_review_id.get(it.review_id) and queue_by_review_id[it.review_id].queue_index is not None
                else 0,
                it.id,
            )
        )
        total = len(all_items)
        start = (page - 1) * page_size
        page_items = all_items[start : start + page_size]

        resp_items = []
        for item in page_items:
            d = item.to_dict()
            q = queue_by_review_id.get(item.review_id)
            d['queue_guid'] = q.queue_guid if q else None
            d['queue_index'] = q.queue_index if q else None
            d['in_mc_export'] = item.decision in (Decision.KEEP, Decision.ADD)
            resp_items.append(d)

        return jsonify(
            {
                'items': resp_items,
                'total': total,
                'page': page,
                'page_size': page_size,
            }
        ), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch queue items: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/skipped-items', methods=['GET'])
def get_skipped_items_for_project(project_guid):
    """
    Virtual queue: aggregate all SKIP-decision items across all reviewer queues for a project.

    Each returned item includes `queue_guid` so the frontend can route decisions back to the
    originating underlying reviewer queue.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()

        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 100, type=int)
        dedupe_source_id = request.args.get('dedupe_source_id', 'true').lower() in ['1', 'true', 'yes', 'y']

        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 100
        # Hard cap to prevent accidental massive responses.
        page_size = min(page_size, 5000)

        queues = Review.query.filter_by(review_project_id=project.id).all()
        queue_ids = [q.id for q in queues]
        if not queue_ids:
            return jsonify({'items': [], 'total': 0}), 200

        queue_by_review_id = {q.id: q for q in queues}

        skipped_query = ReviewItem.query.filter(
            ReviewItem.review_id.in_(queue_ids),
            ReviewItem.decision == Decision.SKIP,
        ).order_by(ReviewItem.id.asc())

        skipped_items = skipped_query.all()

        if dedupe_source_id:
            seen_keys = set()
            deduped = []
            for item in skipped_items:
                # Prefer source_id as the dedupe key; fall back to item id for new-source rows.
                key = item.source_id if item.source_id is not None else f'item:{item.id}'
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped.append(item)
            skipped_items = deduped

        total = len(skipped_items)

        start = (page - 1) * page_size
        end = start + page_size
        page_items = skipped_items[start:end]

        resp_items = []
        for item in page_items:
            item_dict = item.to_dict()
            q = queue_by_review_id.get(item.review_id)
            item_dict['queue_guid'] = q.queue_guid if q else None
            item_dict['queue_index'] = q.queue_index if q else None
            resp_items.append(item_dict)

        return jsonify({'items': resp_items, 'total': total}), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch skipped items: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/added-items', methods=['GET'])
def get_added_items_for_project(project_guid):
    """
    Virtual queue: aggregate all ADD-decision items across all reviewer queues for a project.

    Each returned item includes `queue_guid` and `queue_index` so the frontend can route any
    optional item-level operations back to the originating queue.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()

        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 100, type=int)
        dedupe_source_id = request.args.get('dedupe_source_id', 'true').lower() in ['1', 'true', 'yes', 'y']

        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 100
        page_size = min(page_size, 5000)

        queues = Review.query.filter_by(review_project_id=project.id).all()
        queue_ids = [q.id for q in queues]
        if not queue_ids:
            return jsonify({'items': [], 'total': 0}), 200

        queue_by_review_id = {q.id: q for q in queues}

        added_query = ReviewItem.query.filter(
            ReviewItem.review_id.in_(queue_ids),
            ReviewItem.decision == Decision.ADD,
        ).order_by(ReviewItem.id.asc())

        added_items = added_query.all()

        if dedupe_source_id:
            seen_keys = set()
            deduped = []
            for item in added_items:
                # Prefer source_id as the dedupe key; for new sources (source_id is None),
                # fall back to item id.
                key = item.source_id if item.source_id is not None else f'item:{item.id}'
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped.append(item)
            added_items = deduped

        total = len(added_items)

        start = (page - 1) * page_size
        end = start + page_size
        page_items = added_items[start:end]

        resp_items = []
        for item in page_items:
            item_dict = item.to_dict()
            q = queue_by_review_id.get(item.review_id)
            item_dict['queue_guid'] = q.queue_guid if q else None
            item_dict['queue_index'] = q.queue_index if q else None
            resp_items.append(item_dict)

        return jsonify({'items': resp_items, 'total': total}), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch added items: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/removed-items', methods=['GET'])
def get_removed_items_for_project(project_guid):
    """
    Virtual queue: aggregate all REMOVE-decision items across all reviewer queues for a project.

    Each returned item includes `queue_guid` and `queue_index` so the frontend can route any
    optional item-level operations back to the originating queue.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()

        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 100, type=int)
        dedupe_source_id = request.args.get('dedupe_source_id', 'true').lower() in ['1', 'true', 'yes', 'y']

        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 100
        page_size = min(page_size, 5000)

        queues = Review.query.filter_by(review_project_id=project.id).all()
        queue_ids = [q.id for q in queues]
        if not queue_ids:
            return jsonify({'items': [], 'total': 0}), 200

        queue_by_review_id = {q.id: q for q in queues}

        removed_query = ReviewItem.query.filter(
            ReviewItem.review_id.in_(queue_ids),
            ReviewItem.decision == Decision.REMOVE,
        ).order_by(ReviewItem.id.asc())

        removed_items = removed_query.all()

        if dedupe_source_id:
            seen_keys = set()
            deduped = []
            for item in removed_items:
                # Prefer source_id as the dedupe key; for new sources (source_id is None),
                # fall back to item id.
                key = item.source_id if item.source_id is not None else f'item:{item.id}'
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped.append(item)
            removed_items = deduped

        total = len(removed_items)

        start = (page - 1) * page_size
        end = start + page_size
        page_items = removed_items[start:end]

        resp_items = []
        for item in page_items:
            item_dict = item.to_dict()
            q = queue_by_review_id.get(item.review_id)
            item_dict['queue_guid'] = q.queue_guid if q else None
            item_dict['queue_index'] = q.queue_index if q else None
            resp_items.append(item_dict)

        return jsonify({'items': resp_items, 'total': total}), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch removed items: {str(e)}'}), 500


@api_bp.route('/review-projects/<string:project_guid>/kept-items', methods=['GET'])
def get_kept_items_for_project(project_guid):
    """
    Virtual queue: aggregate all KEEP-decision items across all reviewer queues for a project.

    Each returned item includes `queue_guid` and `queue_index`.
    """
    try:
        project = ReviewProject.query.filter_by(guid=project_guid).first_or_404()

        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 100, type=int)
        dedupe_source_id = request.args.get('dedupe_source_id', 'true').lower() in ['1', 'true', 'yes', 'y']

        if page < 1:
            page = 1
        if page_size < 1:
            page_size = 100
        page_size = min(page_size, 5000)

        queues = Review.query.filter_by(review_project_id=project.id).all()
        queue_ids = [q.id for q in queues]
        if not queue_ids:
            return jsonify({'items': [], 'total': 0}), 200

        queue_by_review_id = {q.id: q for q in queues}

        kept_query = ReviewItem.query.filter(
            ReviewItem.review_id.in_(queue_ids),
            ReviewItem.decision == Decision.KEEP,
        ).order_by(ReviewItem.id.asc())

        kept_items = kept_query.all()

        if dedupe_source_id:
            seen_keys = set()
            deduped = []
            for item in kept_items:
                key = item.source_id if item.source_id is not None else f'item:{item.id}'
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                deduped.append(item)
            kept_items = deduped

        total = len(kept_items)

        start = (page - 1) * page_size
        end = start + page_size
        page_items = kept_items[start:end]

        resp_items = []
        for item in page_items:
            item_dict = item.to_dict()
            q = queue_by_review_id.get(item.review_id)
            item_dict['queue_guid'] = q.queue_guid if q else None
            item_dict['queue_index'] = q.queue_index if q else None
            resp_items.append(item_dict)

        return jsonify({'items': resp_items, 'total': total}), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch kept items: {str(e)}'}), 500


@api_bp.route('/review-queues/<string:queue_guid>/items/<int:item_id>/source-metadata', methods=['PATCH'])
def update_queue_item_source_metadata(queue_guid, item_id):
    """
    Update per-item source metadata JSON (primary_language/pub_country/pub_state).

    Used by the virtual queues to let managers/reviewers tweak metadata on already-added items.
    """
    try:
        queue_review = Review.query.filter_by(queue_guid=queue_guid).first_or_404()

        if not _effective_queue_edit_metadata(queue_review):
            return jsonify({'error': 'Metadata editing is disabled for this queue'}), 403

        item = ReviewItem.query.filter_by(id=item_id, review_id=queue_review.id).first_or_404()

        data = request.get_json() or {}
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        allowed_keys = {'primary_language', 'pub_country', 'pub_state'}
        updates = {k: v for k, v in data.items() if k in allowed_keys}
        if not updates:
            return jsonify({'error': 'No valid metadata fields provided'}), 400

        current_meta = {}
        if item.source_metadata:
            try:
                current_meta = json.loads(item.source_metadata) or {}
            except Exception:
                current_meta = {}

        # Apply updates; allow blank strings (client controls validation where needed).
        for k, v in updates.items():
            current_meta[k] = v

        item.source_metadata = json.dumps(current_meta)
        db.session.commit()

        return jsonify({'item': item.to_dict()}), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update source metadata: {str(e)}'}), 500


@api_bp.route('/review-queues/<string:queue_guid>/guidelines', methods=['GET'])
def get_review_queue_guidelines(queue_guid):
    """
    Get rendered guidelines for a queue (by queue_guid).
    """
    try:
        queue_review = Review.query.filter_by(queue_guid=queue_guid).first_or_404()
        service = get_guidelines_service()

        project = queue_review.review_project
        if project and project.guidelines_custom_markdown:
            return jsonify({'guidelines': project.guidelines_custom_markdown}), 200

        template_name = (project.guidelines_template if project else queue_review.guidelines_template) or 'default'

        # Stable project-level context so guidelines are identical across all reviewer queues.
        primary_collection_id = None
        if project and project.collection_ids_json:
            try:
                ids = json.loads(project.collection_ids_json or '[]')
                primary_collection_id = ids[0] if ids else None
            except Exception:
                primary_collection_id = None

        context_overrides = {
            'collection_name': project.name if project and project.name else queue_review.collection_name,
            'collection_id': primary_collection_id if primary_collection_id is not None else queue_review.collection_id,
            'review_id': project.id if project else queue_review.id,
            'review_name': project.name if project and project.name else queue_review.name,
        }

        guidelines = service.render_guidelines(template_name, queue_review, context_overrides=context_overrides)
        return jsonify({'guidelines': guidelines}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch guidelines: {str(e)}'}), 500


@api_bp.route('/review-queues/<string:queue_guid>', methods=['GET'])
def get_review_queue(queue_guid):
    """
    Get a reviewer queue by GUID.
    Queue status is derived from whether any undecided items remain.
    """
    try:
        queue_review = Review.query.filter_by(queue_guid=queue_guid).first_or_404()

        undecided_count = ReviewItem.query.filter_by(
            review_id=queue_review.id,
            decision=Decision.UNDECIDED
        ).count()

        derived_status = ReviewStatus.COMPLETED.value if undecided_count == 0 else ReviewStatus.IN_PROGRESS.value

        queue_data = queue_review.to_dict(include_stats=True)
        queue_data['status'] = derived_status
        queue_data['undecided_count'] = undecided_count
        queue_data['review_project_guid'] = queue_review.review_project.guid if queue_review.review_project else None
        queue_data['edit_metadata'] = _effective_queue_edit_metadata(queue_review)

        return jsonify({'review': queue_data}), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch queue: {str(e)}'}), 500


@api_bp.route('/review-queues/<string:queue_guid>/items', methods=['GET'])
def get_review_queue_items(queue_guid):
    """
    Get queue items (same behavior as /reviews/<int>/items).
    """
    try:
        queue_review = Review.query.filter_by(queue_guid=queue_guid).first_or_404()

        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 100, type=int)
        decision_filter = request.args.get('decision', None)

        query = ReviewItem.query.filter_by(review_id=queue_review.id)

        if decision_filter:
            try:
                decision_enum = Decision(decision_filter)
                query = query.filter_by(decision=decision_enum)
            except ValueError:
                return jsonify({'error': f'Invalid decision value: {decision_filter}'}), 400

        total = query.count()

        items = query.order_by(ReviewItem.id).offset((page - 1) * page_size).limit(page_size).all()
        return jsonify({
            'items': [item.to_dict() for item in items],
            'total': total
        }), 200

    except Exception as e:
        return jsonify({'error': f'Failed to fetch queue items: {str(e)}'}), 500


@api_bp.route('/review-queues/<string:queue_guid>/items/<int:item_id>', methods=['GET'])
def get_review_queue_item(queue_guid, item_id):
    """
    Get a single queue item by queue_guid + item_id.
    """
    queue_review = Review.query.filter_by(queue_guid=queue_guid).first_or_404()
    item = ReviewItem.query.filter_by(id=item_id, review_id=queue_review.id).first_or_404()
    return jsonify({'item': item.to_dict()}), 200


@api_bp.route('/review-queues/<string:queue_guid>/items/<int:item_id>/decide', methods=['POST'])
def decide_queue_item(queue_guid, item_id):
    """
    Decide on an item in a queue by queue_guid.

    Body: { "decision": "keep"|"remove"|"skip"|..., "removal_reason"?: str (required for remove),
           "skip_note"?: str (optional for skip) }
    """
    try:
        queue_review = Review.query.filter_by(queue_guid=queue_guid).first_or_404()

        item = ReviewItem.query.filter_by(id=item_id, review_id=queue_review.id).first_or_404()

        data = request.get_json() or {}
        if not data or 'decision' not in data:
            return jsonify({'error': 'decision is required'}), 400

        decision_str = data['decision']
        try:
            decision_enum = Decision(decision_str)
        except ValueError:
            return jsonify({'error': f'Invalid decision: {decision_str}. Must be one of: keep, remove, add, undecided, skip'}), 400

        if not item.is_new_source:
            if decision_enum not in [Decision.KEEP, Decision.REMOVE, Decision.SKIP]:
                return jsonify({
                    'error': f'Existing sources can only be marked as "keep", "remove", or "skip", not "{decision_str}"'
                }), 400

        side_effect_error = _apply_review_item_decision_fields(item, decision_enum, data)
        if side_effect_error:
            return jsonify({'error': side_effect_error}), 400

        item.decision = decision_enum
        if decision_enum in [Decision.KEEP, Decision.REMOVE, Decision.ADD]:
            item.decided_at = datetime.utcnow()

        db.session.commit()

        return jsonify(item.to_dict()), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update queue item: {str(e)}'}), 500


@api_bp.route('/review-queues/<string:queue_guid>/items', methods=['POST'])
def create_queue_review_item(queue_guid):
    """
    Propose a new source for a queue.
    """
    try:
        queue_review = Review.query.filter_by(queue_guid=queue_guid).first_or_404()

        data = request.get_json() or {}
        if not data:
            return jsonify({'error': 'Request body is required'}), 400

        source_label = data.get('source_label')
        source_homepage = data.get('source_homepage')

        if not source_label:
            return jsonify({'error': 'source_label is required'}), 400
        if not source_homepage:
            return jsonify({'error': 'source_homepage is required'}), 400

        primary_language = data.get('primary_language')
        pub_country = data.get('pub_country')
        pub_state = data.get('pub_state')

        # If metadata editing is enabled for this queue, require these fields.
        effective_edit_metadata = _effective_queue_edit_metadata(queue_review)

        if effective_edit_metadata:
            if not primary_language or not pub_country or not pub_state:
                return jsonify({
                    'error': 'When metadata editing is enabled, primary_language, pub_country, and pub_state are required.'
                }), 400

        def _normalize_homepage(homepage: str) -> str:
            homepage = (homepage or '').strip()
            homepage = homepage.rstrip('/')
            try:
                parsed = urlparse(homepage)
                if parsed.scheme and parsed.netloc:
                    scheme = (parsed.scheme or '').lower()
                    netloc = (parsed.netloc or '').lower()
                    path = (parsed.path or '').rstrip('/')
                    query = f'?{parsed.query}' if parsed.query else ''
                    return f'{scheme}://{netloc}{path}{query}'
            except Exception:
                pass
            return homepage.lower()

        # Duplicate check within the parent ReviewProject:
        # - compare against all existing ReviewItems (seed + already proposed) across all queues
        # - match by source_homepage only
        if queue_review.review_project_id is not None:
            project_id = queue_review.review_project_id
            queues = Review.query.filter_by(review_project_id=project_id).all()
            queue_ids = [q.id for q in queues]

            proposed_norm = _normalize_homepage(source_homepage)
            existing_items = ReviewItem.query.filter(
                ReviewItem.review_id.in_(queue_ids)
            ).filter(
                ReviewItem.source_homepage.isnot(None)
            ).all()

            for item in existing_items:
                existing_norm = _normalize_homepage(item.source_homepage or '')
                if existing_norm == proposed_norm:
                    return jsonify({'error': 'This source already exists in the ReviewProject'}), 409

        metadata = None
        if effective_edit_metadata and (primary_language or pub_country or pub_state):
            metadata = {
                'primary_language': primary_language,
                'pub_country': pub_country,
                'pub_state': pub_state,
            }

        new_item = ReviewItem(
            review_id=queue_review.id,
            source_id=None,
            source_label=source_label,
            source_homepage=source_homepage,
            is_new_source=True,
            decision=Decision.ADD
        )
        if metadata is not None:
            new_item.source_metadata = json.dumps(metadata)

        db.session.add(new_item)
        db.session.commit()

        return jsonify(new_item.to_dict()), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create queue item: {str(e)}'}), 500


@api_bp.route('/reviews/in-progress', methods=['GET'])
def get_in_progress_reviews():
    """
    Get all reviews that are in progress (not completed).
    
    GET /api/reviews/in-progress
    
    Returns: Array of review objects with completeness percentage
    """
    try:
        # Get all reviews that are not completed
        reviews = Review.query.filter(
            Review.status != ReviewStatus.COMPLETED
        ).filter(
            Review.review_project_id.is_(None)
        ).order_by(Review.created_at.desc()).all()
        
        result = []
        for review in reviews:
            stats = review.calculate_stats()
            total = stats['total']
            
            # Calculate completeness: (decided items / total items) * 100
            # Decided items = total - undecided - skip
            undecided = stats.get('undecided', 0)
            skipped = stats.get('skip', 0)
            decided = total - undecided - skipped
            completeness = (decided / total * 100) if total > 0 else 0
            
            review_data = review.to_dict(include_stats=False)
            review_data['completeness'] = round(completeness, 1)
            review_data['stats'] = stats
            result.append(review_data)
        
        return jsonify({
            'reviews': result
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch in-progress reviews: {str(e)}'}), 500


@api_bp.route('/reviews/completed', methods=['GET'])
def get_completed_reviews():
    """
    Get all completed reviews.
    
    GET /api/reviews/completed
    
    Returns: Array of review objects with completeness percentage
    """
    try:
        # Get all completed reviews
        reviews = Review.query.filter(
            Review.status == ReviewStatus.COMPLETED
        ).filter(
            Review.review_project_id.is_(None)
        ).order_by(Review.updated_at.desc()).all()
        
        result = []
        for review in reviews:
            stats = review.calculate_stats()
            total = stats['total']
            
            # Calculate completeness: (decided items / total items) * 100
            # Decided items = total - undecided - skip
            undecided = stats.get('undecided', 0)
            skipped = stats.get('skip', 0)
            decided = total - undecided - skipped
            completeness = (decided / total * 100) if total > 0 else 0
            
            review_data = review.to_dict(include_stats=False)
            review_data['completeness'] = round(completeness, 1)
            review_data['stats'] = stats
            result.append(review_data)
        
        return jsonify({
            'reviews': result
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch completed reviews: {str(e)}'}), 500


@api_bp.route('/reviews/<int:review_id>', methods=['GET'])
def get_review(review_id):
    """
    Get a review by ID with statistics.
    
    GET /api/reviews/<review_id>
    
    Returns: Review JSON with stats
    """
    try:
        review = Review.query.get_or_404(review_id)
        
        # If collection_name is not set, try to fetch it
        if not review.collection_name:
            try:
                mediacloud = get_mediacloud_service()
                collection_details = mediacloud.fetch_collection_details(review.collection_id)
                review.collection_name = collection_details.get('name', f'Collection {review.collection_id}')
                db.session.commit()
            except Exception:
                # If fetching fails, use default
                review.collection_name = review.collection_name or f'Collection {review.collection_id}'
        
        return jsonify({
            'review': review.to_dict(include_stats=True)
        }), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch review: {str(e)}'}), 500


@api_bp.route('/reviews/<int:review_id>', methods=['PATCH'])
def update_review(review_id):
    """
    Update mutable properties on a review (currently: edit_metadata).
    
    PATCH /api/reviews/<review_id>
    Body: { "edit_metadata": true }
    """
    try:
        review = Review.query.get_or_404(review_id)
        data = request.get_json() or {}
        
        if 'edit_metadata' in data:
            review.edit_metadata = bool(data['edit_metadata'])
        
        db.session.commit()
        
        return jsonify({
            'review': review.to_dict(include_stats=True)
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update review: {str(e)}'}), 500


@api_bp.route('/sources/<int:source_id>', methods=['GET'])
def get_source(source_id):
    """
    Get the latest source metadata from MediaCloud for a given source ID.
    
    GET /api/sources/<source_id>
    
    Returns: { "source": { ...full source data... } }
    """
    try:
        mediacloud = get_mediacloud_service()
        source = mediacloud.fetch_source_by_id(source_id)
        return jsonify({'source': source}), 200
    except Exception as e:
        return jsonify({'error': f'Failed to fetch source {source_id}: {str(e)}'}), 502


@api_bp.route('/reviews/<int:review_id>/items', methods=['GET'])
def get_review_items(review_id):
    """
    Get review items with optional filtering and pagination.
    
    GET /api/reviews/<review_id>/items?page=1&page_size=20&decision=undecided
    
    Returns: Items array and total count
    """
    try:
        # Verify review exists
        review = Review.query.get_or_404(review_id)
        
        # Get query parameters
        page = request.args.get('page', 1, type=int)
        page_size = request.args.get('page_size', 100, type=int)
        decision_filter = request.args.get('decision', None)
        
        # Build query
        query = ReviewItem.query.filter_by(review_id=review_id)
        
        # Apply decision filter if provided
        if decision_filter:
            try:
                decision_enum = Decision(decision_filter)
                query = query.filter_by(decision=decision_enum)
            except ValueError:
                return jsonify({'error': f'Invalid decision value: {decision_filter}'}), 400
        
        # Get total count before pagination
        total = query.count()
        
        # Apply pagination
        items = query.order_by(ReviewItem.id).offset((page - 1) * page_size).limit(page_size).all()
        
        return jsonify({
            'items': [item.to_dict() for item in items],
            'total': total
        }), 200
        
    except Exception as e:
        return jsonify({'error': f'Failed to fetch items: {str(e)}'}), 500


@api_bp.route('/reviews/<int:review_id>/items/<int:item_id>/decide', methods=['POST'])
def decide_item(review_id, item_id):
    """
    Make a decision on a review item.
    
    POST /api/reviews/<review_id>/items/<item_id>/decide
    Body: { "decision": "keep"|"skip"|..., "removal_reason"?: str, "skip_note"?: str (optional for skip) }
    
    Returns: Updated item JSON
    """
    try:
        # Verify review exists
        review = Review.query.get_or_404(review_id)
        
        # Get item and verify it belongs to the review
        item = ReviewItem.query.filter_by(id=item_id, review_id=review_id).first_or_404()
        
        # Get decision from request
        data = request.get_json()
        if not data or 'decision' not in data:
            return jsonify({'error': 'decision is required'}), 400
        
        decision_str = data['decision']
        
        # Validate decision value
        try:
            decision_enum = Decision(decision_str)
        except ValueError:
            return jsonify({'error': f'Invalid decision: {decision_str}. Must be one of: keep, remove, add, undecided, skip'}), 400
        
        # Validate decision based on item type
        if not item.is_new_source:
            # Existing sources can be kept, removed, or skipped
            if decision_enum not in [Decision.KEEP, Decision.REMOVE, Decision.SKIP]:
                return jsonify({
                    'error': f'Existing sources can only be marked as "keep", "remove", or "skip", not "{decision_str}"'
                }), 400
        else:
            # New sources can be added (or removed/keep/skip if desired)
            # The spec says new sources default to "add", but allows other decisions
            pass
        
        side_effect_error = _apply_review_item_decision_fields(item, decision_enum, data)
        if side_effect_error:
            return jsonify({'error': side_effect_error}), 400

        # Update item
        item.decision = decision_enum
        # Mark decided_at for concrete decisions; leave as-is for undecided/skip
        if decision_enum in [Decision.KEEP, Decision.REMOVE, Decision.ADD]:
            item.decided_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify(item.to_dict()), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to update item: {str(e)}'}), 500


@api_bp.route('/reviews/<int:review_id>/items', methods=['POST'])
def create_review_item(review_id):
    """
    Propose a new source for a review.
    
    POST /api/reviews/<review_id>/items
    Body: {
        "source_label": "New Outlet",
        "source_homepage": "https://new-outlet.example"
    }
    
    Returns: Created item JSON
    """
    try:
        # Verify review exists
        review = Review.query.get_or_404(review_id)
        
        # Get data from request
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Request body is required'}), 400
        
        source_label = data.get('source_label')
        source_homepage = data.get('source_homepage')
        
        # Validate required fields
        if not source_label:
            return jsonify({'error': 'source_label is required'}), 400
        if not source_homepage:
            return jsonify({'error': 'source_homepage is required'}), 400

        primary_language = data.get('primary_language')
        pub_country = data.get('pub_country')
        pub_state = data.get('pub_state')

        # If metadata editing is enabled for this review, require these fields.
        if review.edit_metadata:
            if not primary_language or not pub_country or not pub_state:
                return jsonify({
                    'error': 'When metadata editing is enabled, primary_language, pub_country, and pub_state are required.'
                }), 400
        
        # Create new review item
        new_item = ReviewItem(
            review_id=review_id,
            source_id=None,  # New sources don't have a MediaCloud source_id
            source_label=source_label,
            source_homepage=source_homepage,
            is_new_source=True,
            decision=Decision.ADD  # New sources default to "add"
        )

        if review.edit_metadata and (primary_language or pub_country or pub_state):
            new_item.source_metadata = json.dumps({
                'primary_language': primary_language,
                'pub_country': pub_country,
                'pub_state': pub_state
            })
        
        db.session.add(new_item)
        db.session.commit()
        
        return jsonify(new_item.to_dict()), 201
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to create item: {str(e)}'}), 500


@api_bp.route('/reviews/<int:review_id>/complete', methods=['POST'])
def complete_review(review_id):
    """
    Mark a review as completed.
    
    POST /api/reviews/<review_id>/complete
    
    Returns: Updated review JSON
    """
    try:
        review = Review.query.get_or_404(review_id)
        
        # Check for undecided items (warn but don't block)
        undecided_count = sum(1 for item in review.items if item.decision == Decision.UNDECIDED)
        
        if undecided_count > 0:
            # Return warning but still allow completion
            # In a production app, you might want to make this configurable
            pass
        
        # Update review status
        review.status = ReviewStatus.COMPLETED
        review.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return jsonify({
            'review': review.to_dict(include_stats=True),
            'warning': f'{undecided_count} undecided items remain' if undecided_count > 0 else None
        }), 200
        
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Failed to complete review: {str(e)}'}), 500


def _generate_mediacloud_csv(items, collection_id, include_removal_reason=False):
    """
    Helper function to generate MediaCloud format CSV from review items.
    
    Args:
        items: List of ReviewItem objects to export
        collection_id: MediaCloud collection ID
        include_removal_reason: Whether to include removal_reason as an extra column
    
    Returns:
        CSV string content
    """
    # Read MediaCloud CSV columns from file
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    columns_file = os.path.join(base_dir, '..', 'mc_csv_columns.txt')
    
    mc_columns = []
    try:
        with open(columns_file, 'r') as f:
            mc_columns = [line.strip().split('\t')[0].strip() for line in f if line.strip()]
    except FileNotFoundError:
        # Fallback to default columns if file not found
        mc_columns = [
            'id', 'homepage', 'domain', 'url_search_string', 'label', 'notes',
            'platform', 'pub_country', 'pub_state', 'media_type',
            'stories_total', 'stories_per_week', 'last_story', 'primary_language'
        ]
    
    # Add removal_reason column if requested
    if include_removal_reason:
        mc_columns = mc_columns + ['removal_reason']
    
    # Get MediaCloud service for fetching full source data
    mediacloud = get_mediacloud_service()
    
    # Fetch all sources for the collection to get full data
    # This is more efficient than fetching one by one
    try:
        all_sources = mediacloud.fetch_collection_sources(collection_id)
        # Create a lookup dict by source ID
        sources_by_id = {str(s.get('id')): s for s in all_sources}
    except Exception as e:
        # If fetching fails, we'll handle it per item
        sources_by_id = {}
    
    # Create CSV in memory
    output = io.StringIO()
    writer = csv.writer(output)
    
    # Write header with MediaCloud columns
    writer.writerow(mc_columns)
    
    # Write data rows
    for item in items:
        if item.is_new_source:
            # New sources: only homepage and domain
            row = {}
            for col in mc_columns:
                if col == 'homepage':
                    row[col] = item.source_homepage or ''
                elif col == 'domain':
                    # Extract domain from homepage
                    domain = ''
                    if item.source_homepage:
                        try:
                            parsed = urlparse(item.source_homepage)
                            domain = parsed.netloc or ''
                        except:
                            domain = ''
                    row[col] = domain
                elif col == 'removal_reason':
                    row[col] = item.removal_reason or ''
                else:
                    row[col] = ''
            writer.writerow([row.get(col, '') for col in mc_columns])
        else:
            # Existing sources: fetch full data from MediaCloud
            source_data = sources_by_id.get(str(item.source_id), {})
            
            # Map MediaCloud API fields to CSV columns
            row = {}
            homepage = source_data.get('url') or source_data.get('homepage') or source_data.get('media_url') or item.source_homepage or ''
            
            for col in mc_columns:
                # Map common field names
                if col == 'id':
                    row[col] = item.source_id or ''
                elif col == 'homepage':
                    row[col] = homepage
                elif col == 'domain':
                    # Extract from homepage or use domain field
                    domain = source_data.get('domain', '')
                    if not domain and homepage:
                        try:
                            parsed = urlparse(homepage)
                            domain = parsed.netloc or ''
                        except:
                            pass
                    row[col] = domain
                elif col == 'label':
                    row[col] = source_data.get('name') or source_data.get('label') or item.source_label or ''
                elif col == 'removal_reason':
                    row[col] = item.removal_reason or ''
                else:
                    # Use the field name directly from source_data, or empty string
                    row[col] = source_data.get(col, '')
            
            writer.writerow([row.get(col, '') for col in mc_columns])
    
    output.seek(0)
    return output.getvalue()


@api_bp.route('/reviews/<int:review_id>/export', methods=['GET'])
def export_review(review_id):
    """
    Export review decisions as CSV in MediaCloud collection input format.
    Exports sources marked as 'keep' or 'add'.
    
    GET /api/reviews/<review_id>/export
    
    Returns: CSV file with review data in MediaCloud format
    """
    try:
        review = Review.query.get_or_404(review_id)
        
        # Get all items for this review - only export keep and add decisions
        items = ReviewItem.query.filter_by(review_id=review_id).filter(
            ReviewItem.decision.in_([Decision.KEEP, Decision.ADD])
        ).all()
        
        csv_content = _generate_mediacloud_csv(items, review.collection_id, include_removal_reason=False)
        
        # Create Flask response with CSV
        response = Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=review_{review_id}_export.csv'
            }
        )
        
        return response
        
    except Exception as e:
        return jsonify({'error': f'Failed to export review: {str(e)}'}), 500


@api_bp.route('/reviews/<int:review_id>/export/removed', methods=['GET'])
def export_removed_sources(review_id):
    """
    Export removed sources as CSV with all available metadata.
    
    GET /api/reviews/<review_id>/export/removed
    
    Returns: CSV file with removed sources in MediaCloud format, including removal_reason
    """
    try:
        review = Review.query.get_or_404(review_id)
        
        # Get all items marked as removed
        items = ReviewItem.query.filter_by(review_id=review_id).filter(
            ReviewItem.decision == Decision.REMOVE
        ).all()
        
        # Return empty CSV with headers if no items
        csv_content = _generate_mediacloud_csv(items, review.collection_id, include_removal_reason=True)
        
        # Create Flask response with CSV
        response = Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=review_{review_id}_removed_sources.csv'
            }
        )
        
        return response
        
    except Exception as e:
        return jsonify({'error': f'Failed to export removed sources: {str(e)}'}), 500


@api_bp.route('/reviews/<int:review_id>/export/added', methods=['GET'])
def export_added_sources(review_id):
    """
    Export added sources (new sources) as CSV with all available metadata.
    
    GET /api/reviews/<review_id>/export/added
    
    Returns: CSV file with added sources in MediaCloud format
    """
    try:
        review = Review.query.get_or_404(review_id)
        
        # Get all items marked as add (these are new sources)
        items = ReviewItem.query.filter_by(review_id=review_id).filter(
            ReviewItem.decision == Decision.ADD
        ).all()
        
        # Return empty CSV with headers if no items
        csv_content = _generate_mediacloud_csv(items, review.collection_id, include_removal_reason=False)
        
        # Create Flask response with CSV
        response = Response(
            csv_content,
            mimetype='text/csv',
            headers={
                'Content-Disposition': f'attachment; filename=review_{review_id}_added_sources.csv'
            }
        )
        
        return response
        
    except Exception as e:
        return jsonify({'error': f'Failed to export added sources: {str(e)}'}), 500
