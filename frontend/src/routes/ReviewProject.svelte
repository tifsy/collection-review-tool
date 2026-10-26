<script>
  import { onMount } from 'svelte';
  import AllDecisionsModal from '../components/AllDecisionsModal.svelte';
  import ProjectExportPanel from '../components/ProjectExportPanel.svelte';
  import {
    getReviewProject,
    getReviewProjectAllQueueItems,
    generateReviewProjectQueues,
    setReviewProjectName,
    setReviewProjectEditMetadata,
    setReviewProjectReviewerLandingVirtualQueues,
    getReviewProjectGuidelines,
    setReviewProjectGuidelines,
    publishReviewProject,
    previewPublishReviewProject,
    sendAiDecisions,
    getAiDecisionsUrl,
    MEDIACLOUD_SEARCH_BASE_URL,
  } from '../lib/api.js';

  // Projects imported from the AI reviewer: send the decisions back for the final package
  let aiSending = false;
  let aiResult = null;
  let aiError = null;

  async function handleSendAiDecisions() {
    aiSending = true;
    aiError = null;
    aiResult = null;
    try {
      aiResult = await sendAiDecisions(projectGuid);
    } catch (err) {
      aiError = err.response?.data?.error || err.message || 'Could not send the decisions';
    } finally {
      aiSending = false;
    }
  }

  let projectGuid = null;
  let project = null;
  let queues = [];
  let derivedStatus = null;
  let publishEnabled = true;
  let publishMetadataUpdatesEnabled = true;
  let publishTargetApiBaseUrl = 'https://search.mediacloud.org/api/';
  function queueProgressPercent(q) {
    if (!q || !q.stats || !q.stats.total) return 0;
    const total = q.stats.total;
    const undecided = q.stats.undecided || 0;
    const decidedOrDone = Math.max(0, total - undecided);
    return Math.round((decidedOrDone / total) * 100);
  }
  let stats = null;

  let loading = false;
  let error = null;

  let warning = null;
  let showProjectNameEditor = false;
  let projectNameDraft = '';
  let projectNameSaving = false;
  let projectNameError = null;
  let localEditMetadata = false;
  let initialEditMetadata = false;
  let editMetadataSaving = false;
  let editMetadataError = null;
  let queueCount = 2;
  let generatingQueues = false;
  let queueGenError = null;
  let copiedQueueGuid = null;
  let copiedIconTimer = null;
  let showEditMetadataEditor = false;
  let showReviewerLandingVirtualQueues = true;
  let initialShowReviewerLandingVirtualQueues = true;
  let showReviewerLandingVirtualQueuesEditor = false;
  let reviewerLandingVirtualQueuesSaving = false;
  let reviewerLandingVirtualQueuesError = null;

  let showGuidelinesEditor = false;
  let guidelinesLoadError = null;
  let guidelinesLoading = false;
  let guidelinesSaving = false;
  let guidelinesError = null;
  let initialGuidelinesMarkdown = '';
  let guidelinesMarkdown = '';

  /** Collapsible "Project settings" panel */
  let projectSettingsExpanded = false;

  let showProjectDecisionsModal = false;
  let projectDecisionsItems = [];
  let projectDecisionsLoading = false;
  let projectDecisionsTruncation = '';

  let currentPath = window.location.pathname;

  $: canDownloadMainCsv =
    queues.length > 0 && stats != null && (stats.keep || 0) + (stats.add || 0) > 0;
  $: canDownloadAuditCsv = queues.length > 0 && stats != null && (stats.total || 0) > 0;

  function getProjectGuidFromUrl() {
    const match = currentPath.match(/^\/review-projects\/([0-9a-fA-F-]+)$/);
    return match ? match[1] : null;
  }

  function mediacloudCollectionUrl(collectionId) {
    return `${MEDIACLOUD_SEARCH_BASE_URL}/collections/${collectionId}`;
  }

  function mediacloudSourceUrl(sourceId) {
    return `${MEDIACLOUD_SEARCH_BASE_URL}/sources/${sourceId}`;
  }

  async function handlePublishProject(payload) {
    if (!projectGuid) return null;
    const result = await publishReviewProject(projectGuid, payload);
    await loadProject();
    return result;
  }

  async function handlePreviewPublishProject(payload) {
    if (!projectGuid) return null;
    return await previewPublishReviewProject(projectGuid, payload);
  }

  /** Seed collections for display: parallel `collection_ids` / `collection_names` from the API. */
  $: seedCollectionChips =
    project == null
      ? []
      : (project.collection_ids || []).map((id, i) => {
          const names = project.collection_names || [];
          const name = names[i];
          const label = name != null && String(name).trim() !== '' ? name : String(id);
          return { id, label };
        });

  onMount(async () => {
    const params = new URLSearchParams(window.location.search);
    warning = params.get('warning');

    const updatePath = () => {
      currentPath = window.location.pathname;
      projectGuid = getProjectGuidFromUrl();
    };

    window.addEventListener('popstate', updatePath);
    projectGuid = getProjectGuidFromUrl();

    if (projectGuid) {
      await loadProject();
    }

    return () => {
      window.removeEventListener('popstate', updatePath);
    };
  });

  async function loadProject() {
    if (!projectGuid) return;

    loading = true;
    error = null;

    try {
      const data = await getReviewProject(projectGuid);
      project = data.project;
      publishEnabled = data.publish_enabled !== false;
      publishMetadataUpdatesEnabled = data.publish_metadata_updates_enabled !== false;
      publishTargetApiBaseUrl =
        data.publish_target_api_base_url || 'https://search.mediacloud.org/api/';
      projectNameDraft = project?.name || '';
      showProjectNameEditor = false;
      projectNameError = null;
      localEditMetadata = !!project.edit_metadata;
      initialEditMetadata = !!project.edit_metadata;
      showReviewerLandingVirtualQueues = !!project.show_virtual_queue_links_on_reviewer_landing;
      initialShowReviewerLandingVirtualQueues =
        !!project.show_virtual_queue_links_on_reviewer_landing;
      showEditMetadataEditor = false;
      showReviewerLandingVirtualQueuesEditor = false;
      derivedStatus = data.derived_status;
      queues = data.queues || [];
      stats = data.stats || null;
    } catch (err) {
      error = err.response?.data?.error || err.message || 'Failed to load review project';
      console.error('Error loading review project:', err);
    } finally {
      loading = false;
    }
  }

  async function handleGenerateQueues() {
    if (!projectGuid) return;
    generatingQueues = true;
    queueGenError = null;
    try {
      const result = await generateReviewProjectQueues(projectGuid, queueCount);
      warning = result?.warning || null;
      await loadProject();
    } catch (err) {
      queueGenError = err.response?.data?.error || err.message || 'Failed to generate queues';
      console.error('Error generating queues:', err);
    } finally {
      generatingQueues = false;
    }
  }

  function handleStartProjectNameEdit() {
    projectNameDraft = project?.name || '';
    projectNameError = null;
    showProjectNameEditor = true;
  }

  function handleCancelProjectNameEdit() {
    projectNameDraft = project?.name || '';
    projectNameError = null;
    showProjectNameEditor = false;
  }

  async function handleSaveProjectNameEdit() {
    if (!projectGuid || projectNameSaving) return;

    const trimmed = String(projectNameDraft ?? '').trim();
    if (!trimmed) {
      projectNameError = 'Project name cannot be empty.';
      return;
    }

    projectNameSaving = true;
    projectNameError = null;
    try {
      await setReviewProjectName(projectGuid, trimmed);
      await loadProject();
      showProjectNameEditor = false;
    } catch (err) {
      projectNameError =
        err.response?.data?.error || err.message || 'Failed to update project name';
    } finally {
      projectNameSaving = false;
    }
  }

  async function handleSaveReviewerLandingVirtualQueues() {
    if (!projectGuid || reviewerLandingVirtualQueuesSaving) return;

    reviewerLandingVirtualQueuesSaving = true;
    reviewerLandingVirtualQueuesError = null;

    const nextValue = !!showReviewerLandingVirtualQueues;
    try {
      await setReviewProjectReviewerLandingVirtualQueues(projectGuid, nextValue);
      await loadProject();
      showReviewerLandingVirtualQueuesEditor = false;
    } catch (err) {
      reviewerLandingVirtualQueuesError =
        err.response?.data?.error || err.message || 'Failed to update reviewer landing queue links';
      showReviewerLandingVirtualQueues = !nextValue;
    } finally {
      reviewerLandingVirtualQueuesSaving = false;
    }
  }

  function handleStartReviewerLandingVirtualQueuesEdit() {
    showReviewerLandingVirtualQueues = initialShowReviewerLandingVirtualQueues;
    reviewerLandingVirtualQueuesError = null;
    showReviewerLandingVirtualQueuesEditor = true;
  }

  function handleCancelReviewerLandingVirtualQueuesEdit() {
    showReviewerLandingVirtualQueues = initialShowReviewerLandingVirtualQueues;
    reviewerLandingVirtualQueuesError = null;
    showReviewerLandingVirtualQueuesEditor = false;
  }

  async function handleSaveProjectEditMetadata() {
    if (!projectGuid || editMetadataSaving) return;

    editMetadataSaving = true;
    editMetadataError = null;

    const nextValue = !!localEditMetadata;
    try {
      await setReviewProjectEditMetadata(projectGuid, nextValue);
      await loadProject();
      showEditMetadataEditor = false;
    } catch (err) {
      editMetadataError =
        err.response?.data?.error || err.message || 'Failed to update metadata editing';
      // Revert UI if the server update failed.
      localEditMetadata = !nextValue;
    } finally {
      editMetadataSaving = false;
    }
  }

  function handleStartEditMetadataEdit() {
    localEditMetadata = initialEditMetadata;
    editMetadataError = null;
    showEditMetadataEditor = true;
  }

  function handleCancelEditMetadataEdit() {
    localEditMetadata = initialEditMetadata;
    editMetadataError = null;
    showEditMetadataEditor = false;
  }

  async function handleStartGuidelinesEdit() {
    if (!projectGuid || showGuidelinesEditor || guidelinesLoading) return;

    guidelinesLoadError = null;
    guidelinesLoading = true;

    try {
      const resp = await getReviewProjectGuidelines(projectGuid);
      const markdown = resp?.guidelines ?? '';
      initialGuidelinesMarkdown = markdown;
      guidelinesMarkdown = markdown;
      guidelinesError = null;
      showGuidelinesEditor = true;
    } catch (err) {
      guidelinesLoadError = err.response?.data?.error || err.message || 'Failed to load guidelines';
      guidelinesError = null;
    } finally {
      guidelinesLoading = false;
    }
  }

  function handleCancelGuidelinesEdit() {
    guidelinesError = null;
    guidelinesMarkdown = initialGuidelinesMarkdown;
    showGuidelinesEditor = false;
    guidelinesLoadError = null;
  }

  async function handleSaveGuidelinesEdit() {
    if (!projectGuid || guidelinesSaving) return;

    guidelinesError = null;
    guidelinesSaving = true;

    const nextMarkdown = String(guidelinesMarkdown ?? '');
    if (!nextMarkdown.trim()) {
      guidelinesError = 'Guidelines cannot be empty.';
      guidelinesSaving = false;
      return;
    }

    try {
      await setReviewProjectGuidelines(projectGuid, nextMarkdown);
      await loadProject();
      showGuidelinesEditor = false;
    } catch (err) {
      guidelinesError = err.response?.data?.error || err.message || 'Failed to save guidelines';
    } finally {
      guidelinesSaving = false;
    }
  }

  function queueReviewerLink(queueGuid) {
    return `${window.location.origin}/review-projects/${projectGuid}/queues/${queueGuid}`;
  }

  function closeProjectDecisionsModal() {
    showProjectDecisionsModal = false;
  }

  async function openProjectDecisionsPreview() {
    if (!projectGuid) return;
    showProjectDecisionsModal = true;
    projectDecisionsLoading = true;
    projectDecisionsItems = [];
    projectDecisionsTruncation = '';
    try {
      const data = await getReviewProjectAllQueueItems(projectGuid, { page: 1, page_size: 8000 });
      projectDecisionsItems = data.items || [];
      const total = data.total ?? 0;
      const shown = projectDecisionsItems.length;
      if (total > shown) {
        projectDecisionsTruncation = `Showing ${shown} of ${total} rows. Download the audit CSV for the full list.`;
      }
    } catch (err) {
      projectDecisionsItems = [];
      projectDecisionsTruncation =
        err.response?.data?.error || err.message || 'Failed to load queue items.';
    } finally {
      projectDecisionsLoading = false;
    }
  }

  async function copyQueueLink(queueGuid) {
    const link = queueReviewerLink(queueGuid);
    try {
      await navigator.clipboard.writeText(link);
      copiedQueueGuid = queueGuid;
      if (copiedIconTimer) {
        clearTimeout(copiedIconTimer);
      }
      copiedIconTimer = setTimeout(() => {
        copiedQueueGuid = null;
        copiedIconTimer = null;
      }, 1200);
    } catch (e) {
      // Clipboard can fail due to browser permissions; fall back to selection-free UI.
      console.error('Copy failed:', e);
    }
  }
</script>

<div class="container">
  {#if loading && !project}
    <div class="loading">Loading project...</div>
  {:else if error && !project}
    <div class="error-message">{error}</div>
  {:else if project}
    <div class="header-bar">
      <div class="header-left">
        <div class="title">
          ReviewProject: {project.name || projectGuid}
        </div>
      </div>

      <div class="header-right">
        <div class="status-pill status-pill-{derivedStatus}">
          {derivedStatus || project.status || 'pending'}
        </div>
      </div>
    </div>

    {#if warning}
      <div class="warning-banner">{warning}</div>
    {/if}

    <div class="content">
      <div class="admin-workflow-card" role="note" aria-label="Admin workflow guidance">
        <h3>
          Media Cloud Source Review Admin: <span class="project-name-static"
            >{project.name || projectGuid}</span
          >
        </h3>
        <div class="landing-explainer">
          <p>
            <a href="https://search.mediacloud.org/" target="_blank" rel="noopener noreferrer"
              >Media Cloud</a
            >
            is an open research platform for studying online media. In Media Cloud,
            <strong>collections</strong> group sources so researchers and partners can analyze or curate
            them together.
          </p>
          <p>
            This application is for <strong>collections review</strong> workflows: this page provides
            options for configuring and managing your review queues, and for exporting review project
            data.
          </p>
        </div>
        <div class="admin-workflow-steps">
          <div>
            <strong>1.</strong> Configure project settings (guidelines and metadata editing).
          </div>
          <div><strong>2.</strong> Generate reviewer queues and share queue links.</div>
          <div>
            <strong>3.</strong> Monitor queue and project progress, then review virtual queues as needed.
          </div>
          <div><strong>4.</strong> Export final project outputs when review is complete.</div>
        </div>
      </div>

      {#if derivedStatus === 'completed'}
        <div class="project-complete-banner" role="status" aria-live="polite">
          <strong>All reviewer queues are complete.</strong>
          Review virtual queues (skipped, added, removed, kept) and export final project outputs.
        </div>
      {/if}

      <div class="project-meta project-overview">
        <div class="meta-block-seed">
          <div class="meta-row meta-row-seed">
            <div class="meta-label">Seed collections</div>
            <div class="meta-value">
              <div class="seed-collection-chips">
                {#each seedCollectionChips as c, i (String(c.id) + '-' + i)}
                  <a
                    class="seed-collection-chip"
                    href={mediacloudCollectionUrl(c.id)}
                    target="_blank"
                    rel="noopener noreferrer"
                    title="Open this collection in Media Cloud"
                  >
                    {c.label}
                  </a>
                {/each}
              </div>
            </div>
          </div>
          <p class="seed-collections-explainer">
            These are the Media Cloud collections the project was created from. They were used to
            pull in the starting set of sources for review.
          </p>
        </div>

        {#if stats}
          <div class="meta-row">
            <div class="meta-label">Review Status</div>
            <div class="meta-value">
              <div class="status-count-row">
                <div class="status-count">
                  <span class="status-count-label">Total</span>
                  <span class="status-count-value">{stats.total || 0}</span>
                </div>
                <div class="status-count">
                  <span class="status-count-label">Undecided</span>
                  <span class="status-count-value">{stats.undecided || 0}</span>
                </div>
                <div class="status-count">
                  <span class="status-count-label">Keep</span>
                  <span class="status-count-value">{stats.keep || 0}</span>
                </div>
                <div class="status-count">
                  <span class="status-count-label">Skip</span>
                  <span class="status-count-value">{stats.skip || 0}</span>
                </div>
                <div class="status-count">
                  <span class="status-count-label">Remove</span>
                  <span class="status-count-value">{stats.remove || 0}</span>
                </div>
                <div class="status-count status-count-added">
                  <span class="status-count-label">Added</span>
                  <span class="status-count-value">{stats.add || 0}</span>
                </div>
              </div>
            </div>
          </div>
        {/if}

        {#if stats && stats.total > 0}
          <div class="project-progress-row">
            <div class="project-progress-bar">
              <div
                class="seg seg-undecided"
                style={`width: ${((stats.undecided || 0) / stats.total) * 100}%`}
                title={`Undecided: ${stats.undecided || 0}`}
              />
              <div
                class="seg seg-keep"
                style={`width: ${((stats.keep || 0) / stats.total) * 100}%`}
                title={`Keep: ${stats.keep || 0}`}
              />
              <div
                class="seg seg-remove"
                style={`width: ${((stats.remove || 0) / stats.total) * 100}%`}
                title={`Remove: ${stats.remove || 0}`}
              />
              <div
                class="seg seg-skip"
                style={`width: ${((stats.skip || 0) / stats.total) * 100}%`}
                title={`Skipped: ${stats.skip || 0}`}
              />
            </div>
          </div>
        {/if}
        {#if queues.length > 0}
          <div class="virtual-queue-nav-actions">
            <button
              type="button"
              class="queue-open"
              on:click={() => window.navigate(`/review-projects/${projectGuid}/skipped`)}
            >
              Review skipped sources
              {#if stats && stats.skip !== undefined && stats.skip > 0}
                <span class="queue-count">({stats.skip})</span>
              {/if}
            </button>

            <button
              type="button"
              class="queue-copy"
              on:click={() => window.navigate(`/review-projects/${projectGuid}/added`)}
            >
              Review added sources
              {#if stats && stats.add !== undefined && stats.add > 0}
                <span class="queue-count">({stats.add})</span>
              {/if}
            </button>

            <button
              type="button"
              class="queue-copy"
              on:click={() => window.navigate(`/review-projects/${projectGuid}/removed`)}
            >
              Review removed sources
              {#if stats && stats.remove !== undefined && stats.remove > 0}
                <span class="queue-count">({stats.remove})</span>
              {/if}
            </button>

            <button
              type="button"
              class="queue-copy"
              on:click={() => window.navigate(`/review-projects/${projectGuid}/kept`)}
            >
              Review kept sources
              {#if stats && stats.keep !== undefined && stats.keep > 0}
                <span class="queue-count">({stats.keep})</span>
              {/if}
            </button>
          </div>
        {/if}
      </div>

      <div class="project-settings" class:is-collapsed={!projectSettingsExpanded}>
        <div class="project-settings-toolbar">
          <h2 class="section-heading project-settings-title" id="project-settings-heading">
            Project settings
          </h2>
          <button
            type="button"
            class="settings-collapse-toggle"
            on:click={() => (projectSettingsExpanded = !projectSettingsExpanded)}
            aria-expanded={projectSettingsExpanded}
            aria-controls="project-settings-panel"
            aria-label={projectSettingsExpanded
              ? 'Collapse project settings'
              : 'Expand project settings'}
          >
            <span
              class="settings-collapse-chevron"
              class:open={projectSettingsExpanded}
              aria-hidden="true"
            ></span>
            <span class="settings-collapse-label">{projectSettingsExpanded ? 'Hide' : 'Show'}</span>
          </button>
        </div>

        {#if projectSettingsExpanded}
          <div
            id="project-settings-panel"
            class="project-settings-panel"
            role="region"
            aria-labelledby="project-settings-heading"
          >
            <p class="settings-intro">
              Use these when you need to change what reviewers see or whether they can edit source
              metadata. Updates apply to every queue in this project.
            </p>

            <section class="setting-card">
              <div class="setting-card-header">
                <h3 class="setting-card-title">Project name</h3>
                {#if !showProjectNameEditor}
                  <button
                    type="button"
                    class="edit-name-button"
                    on:click={handleStartProjectNameEdit}
                    title="Edit project name"
                    aria-label="Edit project name"
                    disabled={projectNameSaving}
                  >
                    ✎
                  </button>
                {/if}
              </div>
              <p class="setting-card-desc">
                Display name used across admin and reviewer views for this review project.
              </p>
              {#if showProjectNameEditor}
                <div class="guidelines-editor">
                  <input
                    type="text"
                    class="project-name-input"
                    bind:value={projectNameDraft}
                    maxlength="255"
                    disabled={projectNameSaving}
                  />
                  <div class="guidelines-editor-actions">
                    <button
                      type="button"
                      class="cancel-name-button"
                      on:click={handleCancelProjectNameEdit}
                      disabled={projectNameSaving}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      class="save-name-button"
                      on:click={handleSaveProjectNameEdit}
                      disabled={projectNameSaving}
                    >
                      {projectNameSaving ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                  {#if projectNameError}
                    <div class="inline-error">{projectNameError}</div>
                  {/if}
                </div>
              {/if}
            </section>

            <section class="setting-card">
              <div class="setting-card-header">
                <h3 class="setting-card-title">Annotation guidelines</h3>
                {#if !showGuidelinesEditor}
                  <button
                    type="button"
                    class="edit-name-button"
                    on:click={handleStartGuidelinesEdit}
                    title="Edit guidelines"
                    aria-label="Edit guidelines"
                    disabled={loading || guidelinesLoading}
                  >
                    ✎
                  </button>
                {/if}
              </div>
              <p class="setting-card-desc">
                Markdown instructions shown to reviewers while they work through sources. Saving
                custom text replaces the default template for all queues until you change it again.
              </p>
              {#if showGuidelinesEditor}
                <div class="guidelines-editor">
                  <textarea
                    class="guidelines-textarea"
                    bind:value={guidelinesMarkdown}
                    rows="10"
                    disabled={guidelinesLoading || guidelinesSaving}
                  />

                  <div class="guidelines-editor-actions">
                    <button
                      type="button"
                      class="cancel-name-button"
                      on:click={handleCancelGuidelinesEdit}
                      disabled={guidelinesSaving || guidelinesLoading}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      class="save-name-button"
                      on:click={handleSaveGuidelinesEdit}
                      disabled={guidelinesSaving || guidelinesLoading}
                    >
                      {guidelinesSaving ? 'Saving...' : 'Save'}
                    </button>
                  </div>

                  {#if guidelinesLoadError}
                    <div class="inline-error">{guidelinesLoadError}</div>
                  {/if}
                  {#if guidelinesError}
                    <div class="inline-error">{guidelinesError}</div>
                  {/if}
                </div>
              {/if}
            </section>

            <section class="setting-card">
              <div class="setting-card-header">
                <h3 class="setting-card-title">Reviewer landing: project virtual queues</h3>
                {#if !showReviewerLandingVirtualQueuesEditor}
                  <div class="setting-card-header-actions">
                    <span
                      class="setting-status-pill"
                      class:is-on={initialShowReviewerLandingVirtualQueues}
                      class:is-off={!initialShowReviewerLandingVirtualQueues}
                    >
                      {initialShowReviewerLandingVirtualQueues ? 'Shown' : 'Hidden'}
                    </span>
                    <button
                      type="button"
                      class="edit-name-button"
                      on:click={handleStartReviewerLandingVirtualQueuesEdit}
                      title="Change reviewer landing virtual queue links"
                      aria-label="Change reviewer landing virtual queue links"
                    >
                      ✎
                    </button>
                  </div>
                {/if}
              </div>
              <p class="setting-card-desc">
                Controls whether reviewer queue landing pages show links to the project-wide virtual
                queues (skipped, added, removed, kept).
              </p>
              {#if showReviewerLandingVirtualQueuesEditor}
                <div class="metadata-editor-panel">
                  <label
                    class="metadata-edit-toggle"
                    title="Applies to all reviewer queue landing pages in this project"
                  >
                    <input
                      type="checkbox"
                      bind:checked={showReviewerLandingVirtualQueues}
                      disabled={reviewerLandingVirtualQueuesSaving || generatingQueues}
                    />
                    <span class="toggle-slider"></span>
                    <span class="metadata-toggle-label"
                      >Show project virtual queue links on reviewer landing pages</span
                    >
                  </label>
                  <div class="metadata-editor-actions">
                    <button
                      type="button"
                      class="cancel-name-button"
                      on:click={handleCancelReviewerLandingVirtualQueuesEdit}
                      disabled={reviewerLandingVirtualQueuesSaving || generatingQueues}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      class="save-name-button"
                      on:click={handleSaveReviewerLandingVirtualQueues}
                      disabled={reviewerLandingVirtualQueuesSaving || generatingQueues}
                    >
                      {reviewerLandingVirtualQueuesSaving ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                  {#if reviewerLandingVirtualQueuesError}
                    <div class="inline-error">{reviewerLandingVirtualQueuesError}</div>
                  {/if}
                </div>
              {/if}
            </section>

            <section class="setting-card">
              <div class="setting-card-header">
                <h3 class="setting-card-title">Source metadata editing</h3>
                {#if !showEditMetadataEditor}
                  <div class="setting-card-header-actions">
                    <span
                      class="setting-status-pill"
                      class:is-on={initialEditMetadata}
                      class:is-off={!initialEditMetadata}
                    >
                      {initialEditMetadata ? 'On' : 'Off'}
                    </span>
                    <button
                      type="button"
                      class="edit-name-button"
                      on:click={handleStartEditMetadataEdit}
                      title="Change metadata editing"
                      aria-label="Change metadata editing"
                    >
                      ✎
                    </button>
                  </div>
                {/if}
              </div>
              <p class="setting-card-desc">
                When enabled, reviewers must confirm language and publication country/state (or edit
                them) before they can mark a source as Keep. The same setting is applied to every
                reviewer queue in this project.
              </p>
              {#if showEditMetadataEditor}
                <div class="metadata-editor-panel">
                  <label
                    class="metadata-edit-toggle"
                    title="Applies to all reviewer queues in this project"
                  >
                    <input
                      type="checkbox"
                      bind:checked={localEditMetadata}
                      disabled={editMetadataSaving || generatingQueues}
                    />
                    <span class="toggle-slider"></span>
                    <span class="metadata-toggle-label">Require metadata editing in review</span>
                  </label>
                  <div class="metadata-editor-actions">
                    <button
                      type="button"
                      class="cancel-name-button"
                      on:click={handleCancelEditMetadataEdit}
                      disabled={editMetadataSaving || generatingQueues}
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      class="save-name-button"
                      on:click={handleSaveProjectEditMetadata}
                      disabled={editMetadataSaving || generatingQueues}
                    >
                      {editMetadataSaving ? 'Saving...' : 'Save'}
                    </button>
                  </div>
                  {#if editMetadataError}
                    <div class="inline-error">{editMetadataError}</div>
                  {/if}
                </div>
              {/if}
            </section>
          </div>
        {/if}
      </div>

      {#if project?.is_ai_import}
        <section class="ai-panel" aria-labelledby="ai-panel-heading">
          <h2 id="ai-panel-heading">AI review</h2>
          <p>
            This project was imported from the AI reviewer{project.ai_source_url ? ':' : '.'}
            {#if project.ai_source_url}
              <a href={project.ai_source_url} target="_blank" rel="noopener noreferrer">{project.ai_source_url}</a>
            {/if}
            The AI's clear calls arrived filled in, with its reason as the removal reason or skip note; the
            reviewer queues hold what it left for people. When the review is done, send the decisions back:
            the AI reviewer rebuilds the collection and produces the final files for Media Cloud.
          </p>
          <div class="ai-panel-actions">
            <button type="button" on:click={handleSendAiDecisions} disabled={aiSending || !project.ai_callback_url}>
              {aiSending ? 'Sending…' : 'Send decisions to the AI reviewer'}
            </button>
            <a href={getAiDecisionsUrl(projectGuid)} target="_blank" rel="noopener noreferrer">Decisions as JSON</a>
          </div>
          {#if !project.ai_callback_url}
            <p class="ai-panel-note">The AI review did not include a callback address: download the decisions and upload them in the AI reviewer.</p>
          {/if}
          {#if aiError}
            <div class="error">{aiError}</div>
          {/if}
          {#if aiResult}
            <p class="ai-panel-note">
              Sent {aiResult.decisions} decisions.
              {#if aiResult.agreement_rate !== null && aiResult.agreement_rate !== undefined}
                Reviewers agreed with the AI on {Math.round(aiResult.agreement_rate * 100)}% of the calls they checked.
              {/if}
              {#if aiResult.job_id}The AI reviewer is rebuilding the package (job {aiResult.job_id}).{/if}
            </p>
          {/if}
        </section>
      {/if}

      <ProjectExportPanel
        {projectGuid}
        {canDownloadMainCsv}
        {canDownloadAuditCsv}
        onDecisionsPreview={openProjectDecisionsPreview}
        onPublish={handlePublishProject}
        onPreviewPublish={handlePreviewPublishProject}
        projectName={project?.name || ''}
        existingPublishCollection={project?.publish_to_collection || null}
        {mediacloudCollectionUrl}
        {mediacloudSourceUrl}
        {publishEnabled}
        {publishMetadataUpdatesEnabled}
        {publishTargetApiBaseUrl}
      />

      <div class="queues">
        <h2>Reviewer Queues</h2>

        {#if queues.length === 0}
          <p class="reviewer-queues-explainer">
            {#if stats != null && (stats.total ?? 0) > 0}
              This project's {stats.total}
              {stats.total === 1 ? 'source is' : 'sources are'} not yet split into reviewer queues. Use
              the form below to divide them into separate queues—each queue gets its own link so multiple
              reviewers can work in parallel without overlapping assignments.
            {:else}
              Reviewer queues have not been generated yet. Use the form below to split the project's
              sources into separate queues—each queue gets its own link so multiple reviewers can
              work in parallel without overlapping assignments.
            {/if}
          </p>
          <div class="queue-gen-card">
            <div class="queue-gen-title">Generate reviewer queues</div>
            <p class="queue-gen-subtitle">
              Enter how many parallel queues (and reviewer links) you want.
            </p>

            <form class="queue-gen-form" on:submit|preventDefault={handleGenerateQueues}>
              <div class="form-group">
                <label for="queue-count-input">queue_count</label>
                <input
                  id="queue-count-input"
                  type="number"
                  min="1"
                  step="1"
                  bind:value={queueCount}
                  disabled={generatingQueues}
                />
              </div>

              {#if queueGenError}
                <div class="error-banner">{queueGenError}</div>
              {/if}

              <button type="submit" disabled={generatingQueues}>
                {generatingQueues ? 'Generating...' : 'Generate queues'}
              </button>
            </form>
          </div>
        {:else}
          <p class="reviewer-queues-explainer">
            {#if stats != null && (stats.total ?? 0) > 0}
              This project's {stats.total}
              {stats.total === 1 ? 'source is' : 'sources are'} split across
              {queues.length} reviewer {queues.length === 1 ? 'queue' : 'queues'}. Each queue has
              its own link so multiple reviewers can work in parallel without overlapping
              assignments.
            {:else}
              This project is split into {queues.length} reviewer {queues.length === 1
                ? 'queue'
                : 'queues'}. Each queue has its own link so multiple reviewers can work in parallel
              without overlapping assignments.
            {/if}
          </p>
          <div class="queues-grid">
            {#each queues as q}
              <div class="queue-card">
                <div class="queue-top">
                  <div class="queue-title">
                    Queue #{(q.queue_index ?? 0) + 1}
                  </div>
                  <div class="queue-status status-pill status-pill-{q.status}">
                    {q.status}
                  </div>
                </div>

                {#if q.stats}
                  <div class="queue-stats">
                    <div class="stat-line"><strong>{q.stats.total}</strong> total</div>
                    <div class="stat-line"><strong>{q.stats.undecided}</strong> undecided</div>
                    <div class="stat-line"><strong>{q.stats.keep}</strong> keep</div>
                    <div class="stat-line"><strong>{q.stats.remove}</strong> remove</div>
                    <div class="stat-line"><strong>{q.stats.add}</strong> add</div>
                    <div class="stat-line"><strong>{q.stats.skip}</strong> skip</div>
                  </div>

                  <div class="queue-progress">
                    <div class="queue-progress-outer">
                      <div
                        class="queue-progress-inner"
                        style={`width: ${queueProgressPercent(q)}%`}
                      />
                    </div>
                    <div class="queue-progress-label">{queueProgressPercent(q)}% complete</div>
                  </div>
                {/if}

                <div class="queue-link-row">
                  <div class="queue-link-label">Reviewer URL</div>
                  <div class="queue-link-value">
                    <code class="queue-code">{queueReviewerLink(q.queue_guid)}</code>
                    <button
                      type="button"
                      class="queue-copy-icon {copiedQueueGuid === q.queue_guid ? 'is-copied' : ''}"
                      on:click={() => copyQueueLink(q.queue_guid)}
                      title="Copy full reviewer URL"
                      aria-label="Copy full reviewer URL"
                    >
                      {#if copiedQueueGuid === q.queue_guid}
                        ✓
                      {:else}
                        📋
                      {/if}
                    </button>
                  </div>
                </div>

                <div class="queue-actions">
                  <button
                    type="button"
                    class="queue-open"
                    on:click={() =>
                      window.navigate(`/review-projects/${projectGuid}/queues/${q.queue_guid}`)}
                  >
                    Open Queue Landing
                  </button>
                </div>
              </div>
            {/each}
          </div>
        {/if}
      </div>
    </div>

    <AllDecisionsModal
      show={showProjectDecisionsModal}
      items={projectDecisionsItems}
      loading={projectDecisionsLoading}
      modalTitle="Project decisions"
      modalDescription="Each row is one source in a reviewer queue. See Export project on the page for what each download contains."
      showQueueColumn={true}
      showProjectCsvColumn={true}
      showReevaluateAction={false}
      truncationNote={projectDecisionsTruncation}
      on:close={closeProjectDecisionsModal}
    />
  {/if}
</div>

<style>
  .container {
    margin: 0 auto;
    padding: 20px;
    padding-top: 72px;
  }

  .loading {
    text-align: center;
    padding: 40px;
    color: #7f8c8d;
    font-size: 18px;
  }

  .error-message {
    background: #fee;
    color: #c33;
    padding: 20px;
    border-radius: 8px;
    border: 1px solid #fcc;
    text-align: center;
  }

  .warning-banner {
    margin: 18px 0 0;
    background: #fff3cd;
    color: #856404;
    padding: 14px 16px;
    border-radius: 8px;
    border: 1px solid #ffeeba;
  }

  .header-bar {
    position: fixed;
    top: 0;
    inset-inline: 0;
    background: #414a55;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.4);
    z-index: 900;
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 16px;
    padding: 10px 20px;
  }

  .header-left {
    display: flex;
    align-items: center;
    gap: 10px;
    color: white;
    min-width: 0;
  }

  .title {
    font-weight: 700;
    color: #f6f8fa;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
  }

  .status-pill {
    padding: 6px 12px;
    border-radius: 999px;
    font-weight: 600;
    font-size: 13px;
    text-transform: lowercase;
    border: 1px solid rgba(255, 255, 255, 0.15);
    color: #f6f8fa;
  }

  .status-pill-pending {
    background-color: #ecf0f1;
    color: #7f8c8d;
  }

  .status-pill-in_progress {
    background-color: #fff3cd;
    color: #856404;
  }

  .status-pill-completed {
    background-color: #27ae60;
    color: white;
  }

  .content {
    max-width: 1320px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 5px;
    padding-top: 8px;
  }

  .project-meta {
    background: white;
    border-radius: 10px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
    border: 1px solid #d0d7de;
    padding: 16px 18px;
  }

  .admin-workflow-card {
    background: #f5fbff;
    border: 1px solid #cfe2ff;
    border-radius: 10px;
    padding: 14px 16px;
  }

  .admin-workflow-title {
    margin: 0 0 6px 0;
    font-size: 16px;
    font-weight: 800;
    color: #2c3e50;
  }

  .admin-workflow-subtitle {
    margin: 0;
    font-size: 13px;
    color: #4f6478;
    line-height: 1.45;
  }

  .admin-workflow-steps {
    margin-top: 10px;
    display: grid;
    gap: 6px;
    font-size: 13px;
    color: #34495e;
    line-height: 1.45;
  }

  .project-complete-banner {
    background: #eaf8ef;
    border: 1px solid #b7e2c4;
    border-radius: 10px;
    padding: 12px 14px;
    color: #1f7a3d;
    font-size: 14px;
    line-height: 1.4;
  }

  .section-heading {
    margin: 0 0 14px 0;
    font-size: 18px;
    font-weight: 700;
    color: #2c3e50;
  }

  .project-name-static {
    font-weight: 700;
    color: #2c3e50;
    font-size: 15px;
  }

  .virtual-queue-nav-actions {
    margin-top: 16px;
    padding-top: 14px;
    border-top: 1px solid #e6e9ee;
    display: flex;
    gap: 10px;
    justify-content: flex-end;
    flex-wrap: wrap;
  }

  .project-settings {
    background: white;
    border-radius: 10px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
    border: 1px solid #d0d7de;
    padding: 14px 18px 18px;
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .project-settings.is-collapsed {
    padding-bottom: 14px;
  }

  .project-settings-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .project-settings-title {
    margin: 0;
    flex: 1;
    min-width: 0;
  }

  .settings-collapse-toggle {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 8px 12px;
    border-radius: 8px;
    border: 1px solid #d0d7de;
    background: #f6f8fa;
    color: #34495e;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
    flex-shrink: 0;
  }

  .settings-collapse-toggle:hover {
    background: #eef1f4;
    border-color: #c0c7d0;
  }

  .settings-collapse-chevron {
    display: inline-block;
    width: 0;
    height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #5a6c7d;
    transform: rotate(-90deg);
    transition: transform 0.18s ease;
  }

  .settings-collapse-chevron.open {
    transform: rotate(0deg);
  }

  .settings-collapse-label {
    white-space: nowrap;
  }

  .project-settings-panel {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin-top: 14px;
    padding-top: 4px;
    border-top: 1px solid #e6e9ee;
  }

  .settings-intro {
    margin: 0;
    font-size: 14px;
    line-height: 1.45;
    color: #5a6c7d;
  }

  .setting-card {
    border: 1px solid #e6e9ee;
    border-radius: 10px;
    padding: 14px 16px;
    background: #fafbfc;
  }

  .setting-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  .setting-card-title {
    margin: 0;
    font-size: 15px;
    font-weight: 700;
    color: #2c3e50;
  }

  .setting-card-header-actions {
    display: inline-flex;
    align-items: center;
    gap: 10px;
  }

  .setting-status-pill {
    font-size: 12px;
    font-weight: 700;
    padding: 4px 10px;
    border-radius: 999px;
    border: 1px solid #d0d7de;
    text-transform: uppercase;
    letter-spacing: 0.03em;
  }

  .setting-status-pill.is-on {
    background: #eaf8ef;
    color: #1f7a3d;
    border-color: #b7e2c4;
  }

  .setting-status-pill.is-off {
    background: #f3f4f6;
    color: #7f8c8d;
  }

  .setting-card-desc {
    margin: 0 0 12px 0;
    font-size: 13px;
    line-height: 1.5;
    color: #5a6c7d;
  }

  .setting-card .guidelines-editor {
    margin-top: 4px;
  }

  .metadata-editor-panel {
    display: flex;
    flex-direction: column;
    gap: 12px;
    align-items: flex-start;
  }

  .metadata-toggle-label {
    font-size: 14px;
    font-weight: 600;
    color: #34495e;
  }

  .metadata-editor-actions {
    display: flex;
    gap: 10px;
    align-items: center;
    flex-wrap: wrap;
  }

  .meta-block-seed {
    margin-bottom: 8px;
  }

  .meta-row-seed {
    margin-bottom: 0;
    align-items: flex-start;
  }

  .ai-panel {
    margin: 20px 0;
    padding: 16px 18px;
    border: 1px solid #c9d8ec;
    border-radius: 8px;
    background: #f3f7fc;
  }

  .ai-panel h2 {
    margin: 0 0 8px;
    font-size: 18px;
  }

  .ai-panel p {
    margin: 0 0 12px;
    line-height: 1.5;
  }

  .ai-panel-actions {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 16px;
  }

  .ai-panel-note {
    margin-top: 12px;
    color: #3b4b5c;
  }

  .seed-collections-explainer,
  .reviewer-queues-explainer {
    font-size: 13px;
    line-height: 1.5;
    color: #5a6c7d;
  }

  .seed-collections-explainer {
    margin: 6px 0 0 0;
  }

  .reviewer-queues-explainer {
    margin: 4px 0 14px 0;
  }

  .meta-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 8px;
  }

  .meta-label {
    font-size: 12px;
    color: #7f8c8d;
    font-weight: 700;
    text-transform: uppercase;
  }

  .meta-value {
    font-size: 14px;
    color: #2c3e50;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .seed-collection-chips {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    justify-content: flex-end;
  }

  a.seed-collection-chip {
    display: inline-flex;
    align-items: center;
    padding: 6px 10px;
    border-radius: 999px;
    border: 1px solid #d0d7de;
    background: #f6f8fa;
    color: #34495e;
    font-size: 12px;
    font-weight: 600;
    max-width: 360px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-decoration: none;
    cursor: pointer;
    box-sizing: border-box;
  }

  a.seed-collection-chip:hover {
    border-color: #3498db;
    background: #eef6fc;
    color: #2980b9;
  }

  a.seed-collection-chip:focus-visible {
    outline: 2px solid #3498db;
    outline-offset: 2px;
  }

  .edit-name-button {
    width: 28px;
    height: 28px;
    border-radius: 999px;
    border: 1px solid #d0d7de;
    background: #fff;
    color: #34495e;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
  }

  .edit-name-button:hover {
    background-color: #f6f8fa;
  }

  .save-name-button {
    padding: 8px 12px;
    border-radius: 999px;
    border: 1px solid #3498db;
    background-color: #3498db;
    color: white;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
  }

  .save-name-button:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .cancel-name-button {
    padding: 8px 12px;
    border-radius: 999px;
    border: 1px solid #d0d7de;
    background: #fff;
    color: #34495e;
    font-size: 12px;
    font-weight: 700;
    cursor: pointer;
  }

  .cancel-name-button:disabled {
    opacity: 0.65;
    cursor: not-allowed;
  }

  .inline-error {
    margin-top: 6px;
    color: #c0392b;
    font-size: 12px;
    font-weight: 600;
  }

  .guidelines-editor {
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .guidelines-textarea {
    width: 100%;
    min-height: 240px;
    padding: 10px 12px;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    font-size: 13px;
    color: #2c3e50;
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, 'Liberation Mono',
      'Courier New', monospace;
    background: white;
    resize: vertical;
  }

  .project-name-input {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid #d0d7de;
    border-radius: 8px;
    font-size: 13px;
    color: #2c3e50;
    background: white;
  }

  .guidelines-editor-actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
    align-items: center;
  }

  .metadata-edit-toggle {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    position: relative;
    cursor: pointer;
  }

  .metadata-edit-toggle input {
    /* Hide the default checkbox; the slider is the visible control. */
    opacity: 0;
    position: absolute;
    width: 1px;
    height: 1px;
  }

  .toggle-slider {
    width: 44px;
    height: 24px;
    border-radius: 999px;
    background: #ecf0f1;
    border: 1px solid #d0d7de;
    position: relative;
    transition:
      background 0.15s ease,
      border-color 0.15s ease;
  }

  .toggle-slider::before {
    content: '';
    width: 18px;
    height: 18px;
    border-radius: 50%;
    background: white;
    position: absolute;
    top: 50%;
    left: 3px;
    transform: translateY(-50%);
    transition: transform 0.15s ease;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.12);
  }

  .metadata-edit-toggle input:checked + .toggle-slider {
    background: #27ae60;
    border-color: #27ae60;
  }

  .metadata-edit-toggle input:checked + .toggle-slider::before {
    transform: translateY(-50%) translateX(20px);
  }

  .queues h2 {
    margin: 0 0 12px;
    color: #2c3e50;
  }

  .empty-text {
    color: #7f8c8d;
    font-style: italic;
  }

  .queue-gen-card {
    background: white;
    border: 1px solid #d0d7de;
    border-radius: 10px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
    padding: 18px 18px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .queue-gen-title {
    font-weight: 800;
    color: #2c3e50;
    font-size: 16px;
  }

  .queue-gen-subtitle {
    color: #7f8c8d;
    font-size: 13px;
    margin-top: -4px;
    margin-bottom: 4px;
  }

  .queue-gen-form .form-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
    margin-bottom: 12px;
  }

  input[type='number'] {
    width: 100%;
    padding: 10px 12px;
    border: 1px solid #ddd;
    border-radius: 8px;
    font-size: 14px;
  }

  .error-banner {
    background: #fee;
    color: #c33;
    padding: 12px 14px;
    border-radius: 8px;
    border: 1px solid #fcc;
    margin-bottom: 12px;
  }

  button[type='submit'] {
    width: 100%;
    padding: 12px 14px;
    background-color: #3498db;
    border: none;
    border-radius: 8px;
    color: white;
    font-weight: 700;
    cursor: pointer;
  }

  button[type='submit']:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }

  .queues-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 14px;
  }

  .queue-card {
    background: white;
    border: 1px solid #d0d7de;
    border-radius: 10px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
    padding: 16px 16px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .queue-top {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 10px;
  }

  .queue-title {
    font-weight: 700;
    color: #2c3e50;
  }

  .queue-stats {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 4px 14px;
  }

  .queue-progress {
    margin-top: 10px;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .queue-progress-outer {
    width: 100%;
    height: 10px;
    border-radius: 999px;
    background: #ecf0f1;
    border: 1px solid #d0d7de;
    overflow: hidden;
  }

  .queue-progress-inner {
    height: 100%;
    background: #27ae60;
    border-radius: 999px;
    transition: width 0.2s ease;
  }

  .queue-progress-label {
    font-size: 12px;
    color: #7f8c8d;
    font-weight: 700;
    text-transform: lowercase;
  }

  .stat-line {
    font-size: 13px;
    color: #34495e;
  }

  .queue-link-row {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .queue-link-value {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .queue-link-label {
    font-size: 12px;
    color: #7f8c8d;
    font-weight: 700;
    text-transform: uppercase;
  }

  .queue-code {
    flex: 1;
    font-size: 12px;
    color: #3498db;
    background: #f5fbff;
    border: 1px solid rgba(52, 152, 219, 0.2);
    padding: 6px 8px;
    border-radius: 8px;
    word-break: break-all;
  }

  .queue-copy-icon {
    width: 30px;
    height: 30px;
    border-radius: 8px;
    border: 1px solid #d0d7de;
    background-color: #f6f8fa;
    color: #34495e;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    transition:
      color 180ms ease,
      border-color 180ms ease,
      background-color 180ms ease,
      opacity 220ms ease;
  }

  .queue-copy-icon:hover {
    background-color: #eef2f7;
  }

  .queue-copy-icon.is-copied {
    color: #1f7a3d;
    border-color: #b7e2c4;
    background-color: #eaf8ef;
    opacity: 1;
  }

  .queue-actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
  }

  .queue-open {
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid #3498db;
    background-color: #3498db;
    color: white;
    font-weight: 700;
    cursor: pointer;
  }

  .queue-copy {
    padding: 10px 12px;
    border-radius: 8px;
    border: 1px solid #d0d7de;
    background-color: #f6f8fa;
    color: #34495e;
    font-weight: 700;
    cursor: pointer;
  }

  .skipped-sources {
    background: white;
    border: 1px solid #d0d7de;
    border-radius: 10px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
    padding: 16px 16px;
    margin-top: 18px;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .skipped-subtitle {
    color: #7f8c8d;
    font-size: 13px;
    line-height: 1.35;
  }

  .skipped-actions {
    display: flex;
    gap: 10px;
    justify-content: flex-end;
    align-items: center;
  }

  .queue-count {
    margin-left: 8px;
    font-weight: 800;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.95);
  }

  /* Override count color for secondary (light) button */
  .queue-copy .queue-count {
    color: #7f8c8d;
  }

  .project-progress-row {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-top: 14px;
  }

  .project-progress-bar {
    flex: 1;
    height: 12px;
    border-radius: 999px;
    background: #ecf0f1;
    border: 1px solid #d0d7de;
    overflow: hidden;
    display: flex;
  }

  .project-progress-bar .seg {
    height: 100%;
    transition: width 0.2s ease;
  }

  .seg-undecided {
    background: #95a5a6;
  }

  .seg-keep {
    background: #27ae60;
  }

  .seg-remove {
    background: #e74c3c;
  }

  .seg-skip {
    background: #f1c40f;
  }

  .status-count-row {
    display: flex;
    align-items: baseline;
    gap: 18px;
    flex-wrap: wrap;
    justify-content: flex-start;
  }

  .status-count {
    display: inline-flex;
    gap: 8px;
    align-items: baseline;
    white-space: nowrap;
  }

  .status-count-label {
    font-size: 12px;
    color: #7f8c8d;
    font-weight: 800;
    text-transform: lowercase;
  }

  .status-count-value {
    font-size: 14px;
    font-weight: 900;
    color: #2c3e50;
  }

  /* Make the Added count visually separated from the rest. */
  .status-count-added {
    margin-left: 8px;
    padding-left: 10px;
    border-left: 2px solid #d0d7de;
  }
</style>
