/** API client for backend communication */
import axios from 'axios';

// In production (served by Flask), use same-origin /api.
// In local dev, fall back to the Flask dev server directly unless overridden.
const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL || (import.meta.env.DEV ? 'http://localhost:5000/api' : '/api');

export const MEDIACLOUD_SEARCH_BASE_URL = (
  import.meta.env.VITE_MEDIACLOUD_SEARCH_BASE_URL || 'https://search.mediacloud.org'
).replace(/\/+$/, '');

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

/**
 * Start or resume a review for a collection
 * @param {number} collectionId - MediaCloud collection ID
 * @param {string} guidelinesTemplate - Guidelines template name (default: 'default')
 * @returns {Promise} Review object
 */
export async function startReview(
  collectionId,
  guidelinesTemplate = 'default',
  editMetadata = false
) {
  const response = await api.post('/reviews/start', {
    collection_id: collectionId,
    guidelines_template: guidelinesTemplate,
    edit_metadata: !!editMetadata,
  });
  return response.data.review;
}

/**
 * Start a ReviewProject seeded from multiple MediaCloud collections.
 * @param {number[]} collectionIds
 * @param {string} guidelinesTemplate
 * @param {boolean} editMetadata
 * @param {string|null} name
 * @returns {Promise<Object>}
 */
export async function startReviewProject(
  collectionIds,
  guidelinesTemplate = 'default',
  editMetadata = false,
  name = null
) {
  const response = await api.post('/review-projects/start', {
    collection_ids: collectionIds,
    guidelines_template: guidelinesTemplate,
    edit_metadata: !!editMetadata,
    name,
  });
  return response.data;
}

/**
 * Geographic MediaCloud country/collection definitions (vendored JSON).
 * Served from the API so the same base URL and CORS policy apply as for other calls.
 * @returns {Promise<object[]>}
 */
export async function getCountryCollections() {
  const response = await api.get('/meta/country-collections');
  return response.data;
}

/**
 * Step 2: generate reviewer queues for a ReviewProject.
 * @param {string} projectGuid
 * @param {number} queueCount
 */
export async function generateReviewProjectQueues(projectGuid, queueCount) {
  const response = await api.post(`/review-projects/${projectGuid}/queues`, {
    queue_count: queueCount,
  });
  return response.data;
}

/**
 * Step 1 alternative: start a ReviewProject from the collection AI reviewer's AI review.
 * @param {{url?: string, proposal?: object, name?: string}} body
 * @returns {Promise<{project: object, existing_sources: number, new_sources: number, warnings: string[]}>}
 */
export async function importAiReview(body) {
  const response = await api.post('/review-projects/import-ai', body);
  return response.data;
}

/**
 * Get a ReviewProject (manager view).
 * @param {string} projectGuid
 */
export async function getReviewProject(projectGuid) {
  const response = await api.get(`/review-projects/${projectGuid}`);
  return response.data;
}

/**
 * Update whether reviewers can edit per-source metadata for this project's queues.
 * Propagates down to all existing reviewer queues.
 * @param {string} projectGuid
 * @param {boolean} editMetadata
 */
export async function setReviewProjectEditMetadata(projectGuid, editMetadata) {
  const response = await api.patch(`/review-projects/${projectGuid}/edit-metadata`, {
    edit_metadata: !!editMetadata,
  });
  return response.data;
}

/**
 * Toggle whether reviewer queue landing pages show project virtual queue links.
 * @param {string} projectGuid
 * @param {boolean} showLinks
 */
export async function setReviewProjectReviewerLandingVirtualQueues(projectGuid, showLinks) {
  const response = await api.patch(
    `/review-projects/${projectGuid}/reviewer-landing-virtual-queues`,
    {
      show_virtual_queue_links_on_reviewer_landing: !!showLinks,
    }
  );
  return response.data;
}

/**
 * Update a ReviewProject display name.
 * @param {string} projectGuid
 * @param {string} name
 */
export async function setReviewProjectName(projectGuid, name) {
  const response = await api.patch(`/review-projects/${projectGuid}/name`, {
    name: String(name ?? '').trim(),
  });
  return response.data;
}

/**
 * Get the final guidelines Markdown for a ReviewProject.
 * (If customized, returns stored final Markdown; otherwise returns rendered template output.)
 * @param {string} projectGuid
 */
export async function getReviewProjectGuidelines(projectGuid) {
  const response = await api.get(`/review-projects/${projectGuid}/guidelines`);
  return response.data;
}

/**
 * Store final (rendered) guidelines Markdown for a ReviewProject.
 * @param {string} projectGuid
 * @param {string} markdown
 */
export async function setReviewProjectGuidelines(projectGuid, markdown) {
  const response = await api.patch(`/review-projects/${projectGuid}/guidelines`, {
    guidelines: String(markdown ?? ''),
  });
  return response.data;
}

/**
 * Publish a ReviewProject directly to MediaCloud.
 * First publish creates a collection; subsequent publishes sync into existing target.
 * @param {string} projectGuid
 * @param {{api_token: string, collection_name?: string}} payload
 */
export async function publishReviewProject(projectGuid, payload) {
  const response = await api.post(`/review-projects/${projectGuid}/publish`, payload);
  return response.data;
}

/**
 * Build publish preview and run token preflight.
 * @param {string} projectGuid
 * @param {{api_token: string, collection_name?: string}} payload
 */
export async function previewPublishReviewProject(projectGuid, payload) {
  const response = await api.post(`/review-projects/${projectGuid}/publish/preview`, payload);
  return response.data;
}

export function getReviewProjectExportUrl(projectGuid) {
  return `${API_BASE_URL}/review-projects/${projectGuid}/export`;
}

/** CSV with every queue row plus review_decision, removal_reason, reviewer_queue columns. */
export function getReviewProjectAuditExportUrl(projectGuid) {
  return `${API_BASE_URL}/review-projects/${projectGuid}/export/audit`;
}

/**
 * All review items across queues for a project (preview / summaries).
 * @param {string} projectGuid
 * @param {{ page?: number, page_size?: number }} options
 */
export async function getReviewProjectAllQueueItems(projectGuid, options = {}) {
  const params = new URLSearchParams();
  if (options.page) params.append('page', options.page);
  if (options.page_size) params.append('page_size', options.page_size);
  const query = params.toString();
  const url = `/review-projects/${projectGuid}/all-queue-items${query ? `?${query}` : ''}`;
  const response = await api.get(url);
  return response.data;
}

/**
 * Get all ReviewProjects with derived status and aggregated stats.
 * @returns {Promise<{projects: Array}>}
 */
export async function getReviewProjects() {
  const response = await api.get('/review-projects');
  return response.data.projects;
}

/**
 * Get aggregated skipped items for a ReviewProject (virtual queue).
 * Each item includes `queue_guid` so decisions can be routed back.
 * @param {string} projectGuid
 * @param {Object} options - { page, page_size, dedupe_source_id }
 */
export async function getSkippedItemsByProjectGuid(projectGuid, options = {}) {
  const params = new URLSearchParams();
  if (options.page) params.append('page', options.page);
  if (options.page_size) params.append('page_size', options.page_size);
  if (options.dedupe_source_id !== undefined)
    params.append('dedupe_source_id', options.dedupe_source_id);

  const query = params.toString();
  const url = `/review-projects/${projectGuid}/skipped-items${query ? `?${query}` : ''}`;

  const response = await api.get(url);
  return response.data;
}

/**
 * Get aggregated added items for a ReviewProject (virtual queue).
 * Each item includes `queue_guid` so metadata updates can be routed back.
 * @param {string} projectGuid
 * @param {Object} options - { page, page_size, dedupe_source_id }
 */
export async function getAddedItemsByProjectGuid(projectGuid, options = {}) {
  const params = new URLSearchParams();
  if (options.page) params.append('page', options.page);
  if (options.page_size) params.append('page_size', options.page_size);
  if (options.dedupe_source_id !== undefined)
    params.append('dedupe_source_id', options.dedupe_source_id);

  const query = params.toString();
  const url = `/review-projects/${projectGuid}/added-items${query ? `?${query}` : ''}`;

  const response = await api.get(url);
  return response.data;
}

/**
 * Get aggregated removed items for a ReviewProject (virtual queue).
 * Each item includes `queue_guid` so metadata updates can be routed back.
 * @param {string} projectGuid
 * @param {Object} options - { page, page_size, dedupe_source_id }
 */
export async function getRemovedItemsByProjectGuid(projectGuid, options = {}) {
  const params = new URLSearchParams();
  if (options.page) params.append('page', options.page);
  if (options.page_size) params.append('page_size', options.page_size);
  if (options.dedupe_source_id !== undefined)
    params.append('dedupe_source_id', options.dedupe_source_id);

  const query = params.toString();
  const url = `/review-projects/${projectGuid}/removed-items${query ? `?${query}` : ''}`;

  const response = await api.get(url);
  return response.data;
}

/**
 * Get aggregated kept items for a ReviewProject (virtual queue).
 * Each item includes `queue_guid` so follow-up actions can be routed back.
 * @param {string} projectGuid
 * @param {Object} options - { page, page_size, dedupe_source_id }
 */
export async function getKeptItemsByProjectGuid(projectGuid, options = {}) {
  const params = new URLSearchParams();
  if (options.page) params.append('page', options.page);
  if (options.page_size) params.append('page_size', options.page_size);
  if (options.dedupe_source_id !== undefined)
    params.append('dedupe_source_id', options.dedupe_source_id);

  const query = params.toString();
  const url = `/review-projects/${projectGuid}/kept-items${query ? `?${query}` : ''}`;

  const response = await api.get(url);
  return response.data;
}

/**
 * Update per-item source metadata for a queue item.
 * @param {string} queueGuid
 * @param {number} itemId
 * @param {{primary_language?: string, pub_country?: string, pub_state?: string}} metadata
 */
export async function updateQueueItemSourceMetadata(queueGuid, itemId, metadata) {
  const response = await api.patch(
    `/review-queues/${queueGuid}/items/${itemId}/source-metadata`,
    metadata
  );
  return response.data;
}

/**
 * Get a reviewer queue review by queue GUID.
 * @param {string} queueGuid
 */
export async function getReviewByQueueGuid(queueGuid) {
  const response = await api.get(`/review-queues/${queueGuid}`);
  return response.data.review;
}

export async function getReviewItemsByQueueGuid(queueGuid, options = {}) {
  const params = new URLSearchParams();
  if (options.page) params.append('page', options.page);
  if (options.page_size) params.append('page_size', options.page_size);
  if (options.decision) params.append('decision', options.decision);

  const response = await api.get(`/review-queues/${queueGuid}/items?${params.toString()}`);
  return response.data;
}

export async function getReviewItemByQueueGuid(queueGuid, itemId) {
  const response = await api.get(`/review-queues/${queueGuid}/items/${itemId}`);
  return response.data.item;
}

export async function decideQueueItem(
  queueGuid,
  itemId,
  decision,
  removalReason = null,
  skipNote = null
) {
  const body = { decision };
  if (decision === 'remove' && removalReason) {
    body.removal_reason = removalReason;
  }
  if (decision === 'skip' && skipNote != null && String(skipNote).trim() !== '') {
    body.skip_note = String(skipNote).trim();
  }

  const response = await api.post(`/review-queues/${queueGuid}/items/${itemId}/decide`, body);
  return response.data;
}

export async function proposeNewSourceByQueueGuid(
  queueGuid,
  sourceLabel,
  sourceHomepage,
  metadata = null
) {
  const body = {
    source_label: sourceLabel,
    source_homepage: sourceHomepage,
  };

  if (metadata) {
    body.primary_language = metadata.primary_language;
    body.pub_country = metadata.pub_country;
    body.pub_state = metadata.pub_state;
  }

  const response = await api.post(`/review-queues/${queueGuid}/items`, body);
  return response.data;
}

export async function getReviewQueueGuidelines(queueGuid) {
  const response = await api.get(`/review-queues/${queueGuid}/guidelines`);
  return response.data.guidelines;
}

/**
 * Get all in-progress reviews
 * @returns {Promise} Array of review objects with completeness percentage
 */
export async function getInProgressReviews() {
  const response = await api.get('/reviews/in-progress');
  return response.data.reviews;
}

/**
 * Get all completed reviews
 * @returns {Promise} Array of review objects with completeness percentage
 */
export async function getCompletedReviews() {
  const response = await api.get('/reviews/completed');
  return response.data.reviews;
}

/**
 * Get a review by ID
 * @param {number} reviewId - Review ID
 * @returns {Promise} Review object with stats
 */
export async function getReview(reviewId) {
  const response = await api.get(`/reviews/${reviewId}`);
  return response.data.review;
}

/**
 * Get review items with optional filters
 * @param {number} reviewId - Review ID
 * @param {Object} options - Query options (page, page_size, decision)
 * @returns {Promise} Object with items array and total count
 */
export async function getReviewItems(reviewId, options = {}) {
  const params = new URLSearchParams();
  if (options.page) params.append('page', options.page);
  if (options.page_size) params.append('page_size', options.page_size);
  if (options.decision) params.append('decision', options.decision);

  const response = await api.get(`/reviews/${reviewId}/items?${params.toString()}`);
  return response.data;
}

/**
 * Make a decision on a review item
 * @param {number} reviewId - Review ID
 * @param {number} itemId - Item ID
 * @param {string} decision - Decision (keep, remove, add, undecided)
 * @param {string} removalReason - Reason for removal (required when decision is 'remove')
 * @returns {Promise} Updated item object
 */
export async function decideItem(
  reviewId,
  itemId,
  decision,
  removalReason = null,
  skipNote = null
) {
  const body = { decision };
  if (decision === 'remove' && removalReason) {
    body.removal_reason = removalReason;
  }
  if (decision === 'skip' && skipNote != null && String(skipNote).trim() !== '') {
    body.skip_note = String(skipNote).trim();
  }
  const response = await api.post(`/reviews/${reviewId}/items/${itemId}/decide`, body);
  return response.data;
}

/**
 * Propose a new source for a review
 * @param {number} reviewId - Review ID
 * @param {string} sourceLabel - Source label/name
 * @param {string} sourceHomepage - Source homepage URL
 * @returns {Promise} Created item object
 */
export async function proposeNewSource(reviewId, sourceLabel, sourceHomepage, metadata = null) {
  const body = {
    source_label: sourceLabel,
    source_homepage: sourceHomepage,
  };

  if (metadata) {
    body.primary_language = metadata.primary_language;
    body.pub_country = metadata.pub_country;
    body.pub_state = metadata.pub_state;
  }

  const response = await api.post(`/reviews/${reviewId}/items`, body);
  return response.data;
}

/**
 * Complete a review
 * @param {number} reviewId - Review ID
 * @returns {Promise} Updated review object
 */
export async function completeReview(reviewId) {
  const response = await api.post(`/reviews/${reviewId}/complete`);
  return response.data.review;
}

/**
 * Get CSV export URL for a review (keep and add sources)
 * @param {number} reviewId - Review ID
 * @returns {string} Export URL
 */
export function getExportUrl(reviewId) {
  return `${API_BASE_URL}/reviews/${reviewId}/export`;
}

/**
 * Get CSV export URL for removed sources
 * @param {number} reviewId - Review ID
 * @returns {string} Export URL
 */
export function getRemovedSourcesExportUrl(reviewId) {
  return `${API_BASE_URL}/reviews/${reviewId}/export/removed`;
}

/**
 * Get CSV export URL for added sources
 * @param {number} reviewId - Review ID
 * @returns {string} Export URL
 */
export function getAddedSourcesExportUrl(reviewId) {
  return `${API_BASE_URL}/reviews/${reviewId}/export/added`;
}

/**
 * Get available guideline templates
 * @returns {Promise} Array of template names
 */
export async function getGuidelineTemplates() {
  const response = await api.get('/guidelines/templates');
  return response.data.templates;
}

/**
 * Get rendered guidelines for a review
 * @param {number} reviewId - Review ID
 * @returns {Promise} Guidelines text (markdown)
 */
export async function getReviewGuidelines(reviewId) {
  const response = await api.get(`/reviews/${reviewId}/guidelines`);
  return response.data.guidelines;
}

/**
 * Update mutable fields on a review
 * @param {number} reviewId - Review ID
 * @param {Object} payload - Fields to update (e.g., { edit_metadata: true })
 * @returns {Promise} Updated review object with stats
 */
export async function updateReview(reviewId, payload) {
  const response = await api.patch(`/reviews/${reviewId}`, payload);
  return response.data.review;
}

/**
 * Get live source details from MediaCloud via backend
 * @param {number} sourceId - MediaCloud source ID
 * @returns {Promise} Source object with latest metadata
 */
export async function getSourceDetails(sourceId) {
  const response = await api.get(`/sources/${sourceId}`);
  return response.data.source;
}
