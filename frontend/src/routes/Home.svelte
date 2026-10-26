<script>
  import { onMount } from 'svelte';
  import {
    startReview,
    startReviewProject,
    getInProgressReviews,
    getCompletedReviews,
    getGuidelineTemplates,
    getReviewProjects,
    getCountryCollections,
    importAiReview,
    generateReviewProjectQueues,
  } from '../lib/api.js';

  // Import an AI review (from the AI reviewer: /api/collections/<key>/proposal.json)
  let showImportAi = false;
  let aiUrl = '';
  let aiName = '';
  let aiQueueCount = 2;
  let aiLoading = false;
  let aiError = null;

  async function handleAiImport() {
    aiLoading = true;
    aiError = null;
    try {
      const result = await importAiReview({ url: aiUrl.trim(), name: aiName.trim() || undefined });
      const guid = result.project.guid;
      await generateReviewProjectQueues(guid, Math.max(1, Number(aiQueueCount) || 1));
      window.navigate(`/review-projects/${guid}`);
    } catch (err) {
      aiError = err.response?.data?.error || err.message || 'Could not import the AI review';
      console.error('Error importing AI review:', err);
    } finally {
      aiLoading = false;
    }
  }

  let collectionId = '';
  let projectCollectionIdsInput = '';
  let loading = false;
  let projectLoading = false;
  let error = null;
  let projectError = null;
  let inProgressReviews = [];
  let loadingReviews = false;
  let completedReviews = [];
  let loadingCompleted = false;
  let showCompleted = false;
  let reviewProjects = [];
  let loadingProjects = false;
  let showStartProject = false;
  let togglingStartProject = false;
  let startFormResourcesReady = false;
  /** @type {Promise<void> | null} */
  let startFormLoadPromise = null;
  let guidelineTemplates = [];
  let selectedTemplate = 'default';
  let loadingTemplates = false;
  let editMetadata = false;
  let projectName = '';

  /** 'manual' | 'geographic' */
  let projectInputMode = 'manual';
  let geoData = [];
  let geoLoading = false;
  let geoLoadError = null;
  let selectedCountryIndex = 0;
  /** @type {number[]} */
  let selectedGeoIds = [];

  onMount(async () => {
    const importUrl = new URLSearchParams(window.location.search).get('import');
    if (importUrl) {
      aiUrl = importUrl;
      showImportAi = true;
    }
    await loadReviewProjects();
  });

  async function ensureStartFormResources() {
    if (startFormResourcesReady) return;
    if (!startFormLoadPromise) {
      startFormLoadPromise = (async () => {
        try {
          await Promise.all([loadGuidelineTemplates(), loadGeoCollections()]);
          startFormResourcesReady = true;
        } finally {
          startFormLoadPromise = null;
        }
      })();
    }
    await startFormLoadPromise;
  }

  async function toggleStartProject() {
    if (togglingStartProject) return;
    const opening = !showStartProject;
    if (opening) {
      togglingStartProject = true;
      try {
        await ensureStartFormResources();
      } catch (err) {
        console.error('Error loading new-project form data:', err);
      } finally {
        togglingStartProject = false;
      }
    }
    showStartProject = opening;
  }

  async function loadGeoCollections() {
    geoLoading = true;
    geoLoadError = null;
    try {
      const raw = await getCountryCollections();
      if (!Array.isArray(raw)) {
        throw new Error('Invalid geographic collections data');
      }
      geoData = [...raw].sort((a, b) =>
        String(a?.country?.name || '').localeCompare(String(b?.country?.name || ''), undefined, {
          sensitivity: 'base',
        })
      );
      selectedCountryIndex = 0;
      applyDefaultGeoSelection();
    } catch (err) {
      console.error('Error loading geographic collections:', err);
      geoLoadError = err?.message || 'Failed to load country list';
      geoData = [];
    } finally {
      geoLoading = false;
    }
  }

  function applyDefaultGeoSelection() {
    const entry = geoData[selectedCountryIndex];
    if (!entry?.collections?.length) {
      selectedGeoIds = [];
      return;
    }
    const nat = entry.country?.national_tags_id;
    const inCountry = new Set(entry.collections.map((c) => c.tags_id));
    if (nat != null && inCountry.has(nat)) {
      selectedGeoIds = [nat];
    } else {
      selectedGeoIds = [entry.collections[0].tags_id];
    }
  }

  function onGeoCountryChange() {
    applyDefaultGeoSelection();
  }

  function toggleGeoCollection(tagsId) {
    if (selectedGeoIds.includes(tagsId)) {
      selectedGeoIds = selectedGeoIds.filter((id) => id !== tagsId);
    } else {
      selectedGeoIds = [...selectedGeoIds, tagsId];
    }
  }

  $: currentGeoEntry = geoData.length ? geoData[selectedCountryIndex] : null;

  async function loadGuidelineTemplates() {
    loadingTemplates = true;
    try {
      guidelineTemplates = await getGuidelineTemplates();
      if (guidelineTemplates.length > 0 && !guidelineTemplates.includes(selectedTemplate)) {
        selectedTemplate = guidelineTemplates[0];
      }
    } catch (err) {
      console.error('Error loading templates:', err);
    } finally {
      loadingTemplates = false;
    }
  }

  async function loadInProgressReviews() {
    loadingReviews = true;
    try {
      inProgressReviews = await getInProgressReviews();
    } catch (err) {
      console.error('Error loading in-progress reviews:', err);
    } finally {
      loadingReviews = false;
    }
  }

  async function loadCompletedReviews() {
    if (completedReviews.length > 0) {
      // Already loaded, just toggle visibility
      showCompleted = !showCompleted;
      return;
    }

    loadingCompleted = true;
    try {
      completedReviews = await getCompletedReviews();
      showCompleted = true;
    } catch (err) {
      console.error('Error loading completed reviews:', err);
    } finally {
      loadingCompleted = false;
    }
  }

  async function loadReviewProjects() {
    loadingProjects = true;
    try {
      reviewProjects = await getReviewProjects();
    } catch (err) {
      console.error('Error loading review projects:', err);
      reviewProjects = [];
    } finally {
      loadingProjects = false;
    }
  }

  function formatDate(dateString) {
    if (!dateString) return 'Unknown';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function navigateToReview(reviewId) {
    window.navigate(`/reviews/${reviewId}`);
  }

  function handleKeydown(event, reviewId) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      navigateToReview(reviewId);
    }
  }

  async function handleSubmit() {
    // Convert to string and trim if it's a number
    const idStr = String(collectionId || '').trim();
    if (!idStr) {
      error = 'Please enter a collection ID';
      return;
    }

    const id = parseInt(idStr);
    if (isNaN(id) || id <= 0) {
      error = 'Collection ID must be a positive number';
      return;
    }

    loading = true;
    error = null;

    try {
      const review = await startReview(id, selectedTemplate, editMetadata);
      await loadInProgressReviews(); // Refresh the list
      window.navigate(`/reviews/${review.id}`);
    } catch (err) {
      error = err.response?.data?.error || err.message || 'Failed to start review';
      console.error('Error starting review:', err);
    } finally {
      loading = false;
    }
  }

  async function handleProjectSubmit() {
    projectError = null;

    let collectionIds = [];

    if (projectInputMode === 'geographic') {
      if (geoLoadError || !geoData.length) {
        projectError =
          'Geographic collections list is not available. Use manual collection IDs or refresh the page.';
        return;
      }
      if (!selectedGeoIds.length) {
        projectError = 'Select at least one geographic collection for this country.';
        return;
      }
      collectionIds = [...new Set(selectedGeoIds)];
      if (collectionIds.some((id) => !Number.isFinite(id) || id <= 0)) {
        projectError = 'Invalid geographic collection selection.';
        return;
      }
    } else {
      const raw = String(projectCollectionIdsInput || '');
      const parts = raw
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

      if (parts.length === 0) {
        projectError = 'Please enter at least one collection ID (comma-separated).';
        return;
      }

      try {
        collectionIds = parts.map((p) => parseInt(p, 10));
      } catch {
        projectError = 'All collection IDs must be valid integers.';
        return;
      }

      if (collectionIds.some((id) => !id || id <= 0)) {
        projectError = 'All collection IDs must be positive integers.';
        return;
      }
    }

    projectLoading = true;
    try {
      const cleanProjectName = String(projectName || '').trim();
      const result = await startReviewProject(
        collectionIds,
        selectedTemplate,
        editMetadata,
        cleanProjectName || null
      );
      const guid = result?.project?.guid;
      if (!guid) {
        projectError = 'Project start succeeded but no project GUID was returned.';
        return;
      }
      // Any warnings are returned on the project page.
      window.navigate(`/review-projects/${guid}`);
    } catch (err) {
      projectError = err.response?.data?.error || err.message || 'Failed to start review project';
      console.error('Error starting review project:', err);
    } finally {
      projectLoading = false;
    }
  }
</script>

<div class="container">
  <div class="main-content">
    <div class="card landing-card">
      <header class="landing-header">
        <h1>MediaCloud Collections Review</h1>
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
            This application is for <strong>collections review</strong> workflows: coordinators create
            review projects from those collections, split work into reviewer queues, and reviewers record
            decisions such as keep, skip, or remove on individual sources. If you were invited to review,
            open your project in the table below and follow the links to your queue from the project
            page. Starting a brand-new project is usually only for coordinators setting up a review.
          </p>
        </div>
        <p class="landing-lead">Open a review project from the table below.</p>
      </header>

      <section class="projects-primary" aria-labelledby="projects-heading">
        <div class="reviews-list-header">
          <h2 id="projects-heading">Review projects</h2>
          <button
            type="button"
            class="toggle-button toggle-button-refresh"
            on:click={loadReviewProjects}
            disabled={loadingProjects}
          >
            {loadingProjects ? 'Loading…' : 'Refresh'}
          </button>
        </div>

        {#if loadingProjects}
          <p class="loading-text">Loading projects…</p>
        {:else if reviewProjects.length === 0}
          <p class="empty-text">No review projects found.</p>
        {:else}
          <div class="projects-table-wrap">
            <table class="projects-table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Queues</th>
                  <th>Total</th>
                  <th>Keep</th>
                  <th>Remove</th>
                  <th>Add</th>
                  <th>Undecided</th>
                  <th>Skip</th>
                  <th>Open</th>
                </tr>
              </thead>
              <tbody>
                {#each reviewProjects as p}
                  <tr>
                    <td class="projects-name">
                      {p.name || p.guid}
                    </td>
                    <td class="projects-status">
                      {p.derived_status}
                    </td>
                    <td>{p.queues_count}</td>
                    <td>{p.stats.total}</td>
                    <td>{p.stats.keep}</td>
                    <td>{p.stats.remove}</td>
                    <td>{p.stats.add}</td>
                    <td>{p.stats.undecided}</td>
                    <td>{p.stats.skip}</td>
                    <td>
                      <button
                        type="button"
                        class="projects-open"
                        on:click={() => window.navigate(`/review-projects/${p.guid}`)}
                      >
                        Open
                      </button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {/if}
      </section>

      <div class="start-project-footer">
        <button type="button" class="text-link-btn" on:click={() => (showImportAi = !showImportAi)}>
          {showImportAi ? 'Hide AI review import' : 'Import an AI review'}
        </button>
      </div>

      {#if showImportAi}
        <div class="project-divider" />
        <div class="project-section">
          <h2>Import an AI review</h2>
          <p class="subtitle">
            Start a project from a collection the AI reviewer has checked. Its clear calls arrive
            filled in with the AI's reason, so reviewers only get what the AI could not settle; the
            reasons are listed in the project's guidelines.
          </p>
          <form on:submit|preventDefault={handleAiImport}>
            <div class="form-group">
              <label for="ai-url">AI review address</label>
              <input
                id="ai-url"
                type="url"
                bind:value={aiUrl}
                placeholder="https://ai-reviewer.example.org/api/collections/34412288/proposal.json"
                required
                disabled={aiLoading}
              />
            </div>
            <div class="form-group">
              <label for="ai-name">Project name (optional)</label>
              <input id="ai-name" type="text" bind:value={aiName} disabled={aiLoading} />
            </div>
            <div class="form-group">
              <label for="ai-queues">Reviewer queues</label>
              <input id="ai-queues" type="number" min="1" bind:value={aiQueueCount} disabled={aiLoading} />
            </div>
            {#if aiError}
              <div class="error">{aiError}</div>
            {/if}
            <button type="submit" disabled={aiLoading || !aiUrl.trim()}>
              {aiLoading ? 'Importing…' : 'Import and create queues'}
            </button>
          </form>
        </div>
      {/if}

      <div class="start-project-footer">
        <button
          type="button"
          class="text-link-btn"
          on:click={toggleStartProject}
          disabled={togglingStartProject}
        >
          {#if togglingStartProject}
            Loading…
          {:else if showStartProject}
            Hide new project form
          {:else}
            Start a new review project
          {/if}
        </button>
      </div>

      {#if showStartProject}
        <div class="project-divider" />
        <p class="start-project-caution">
          <strong>Are you sure you need to be here?</strong>
          If you were asked to review sources, you almost always want an existing project from the list
          above—not this next step. Starting a new review project is for people who are
          <em>seeding</em> collections into new reviewer queues (typically coordinators). If that is
          not you, find your review project in the list above.
        </p>
        <div class="project-section">
          <h2>Start review project</h2>
          <p class="subtitle">Seed a multi-collection project into reviewer queues.</p>

          <form on:submit|preventDefault={handleProjectSubmit}>
            {#if guidelineTemplates.length > 0}
              <div class="form-group">
                <label for="guideline-template">Annotation Guidelines Template</label>
                <select
                  id="guideline-template"
                  bind:value={selectedTemplate}
                  disabled={projectLoading || loadingTemplates}
                >
                  {#each guidelineTemplates as template}
                    <option value={template}>{template}</option>
                  {/each}
                </select>
              </div>
            {/if}

            <div class="form-group">
              <label for="project-name">Project Name</label>
              <input
                id="project-name"
                type="text"
                bind:value={projectName}
                placeholder="e.g. UNDP 2026 Seed Project"
                disabled={projectLoading}
              />
            </div>

            <div class="form-group">
              <span class="field-label">Collection source</span>
              <div class="input-mode-row">
                <label class="input-mode-option">
                  <input
                    type="radio"
                    name="project-input-mode"
                    value="geographic"
                    bind:group={projectInputMode}
                    disabled={projectLoading}
                  />
                  Geographic (MediaCloud country list)
                </label>
                <label class="input-mode-option">
                  <input
                    type="radio"
                    name="project-input-mode"
                    value="manual"
                    bind:group={projectInputMode}
                    disabled={projectLoading}
                  />
                  Manual collection IDs
                </label>
              </div>
            </div>

            {#if projectInputMode === 'geographic'}
              <div class="form-group">
                <label for="geo-country">Country</label>
                {#if geoLoading}
                  <p class="geo-status">Loading countries…</p>
                {:else if geoLoadError}
                  <p class="geo-status error-inline">{geoLoadError}</p>
                  <button
                    type="button"
                    class="secondary-btn"
                    on:click={loadGeoCollections}
                    disabled={projectLoading || geoLoading}
                  >
                    Retry
                  </button>
                {:else}
                  <select
                    id="geo-country"
                    bind:value={selectedCountryIndex}
                    on:change={onGeoCountryChange}
                    disabled={projectLoading || !geoData.length}
                  >
                    {#each geoData as entry, idx (entry.country?.alpha3 || idx)}
                      <option value={idx}>{entry.country?.name || 'Unknown'}</option>
                    {/each}
                  </select>
                  {#if currentGeoEntry}
                    <p class="geo-hint">
                      Choose one or more geographic collections (national, state &amp; local, etc.).
                      List is vendored from MediaCloud web-search <code
                        >country-collections.json</code
                      > and served by this app&apos;s API.
                    </p>
                    <div class="geo-collections-list">
                      {#each currentGeoEntry.collections || [] as col (col.tags_id + '-' + col.tag)}
                        <label class="geo-check">
                          <input
                            type="checkbox"
                            checked={selectedGeoIds.includes(col.tags_id)}
                            on:change={() => toggleGeoCollection(col.tags_id)}
                            disabled={projectLoading}
                          />
                          <span class="geo-check-label">{col.label}</span>
                          <span class="geo-tag-id">{col.tags_id}</span>
                        </label>
                      {/each}
                    </div>
                  {/if}
                {/if}
              </div>
            {:else}
              <div class="form-group">
                <label for="project-collection-ids">MediaCloud Collection IDs</label>
                <input
                  id="project-collection-ids"
                  type="text"
                  bind:value={projectCollectionIdsInput}
                  placeholder="e.g. 123, 456, 789"
                  disabled={projectLoading}
                />
              </div>
            {/if}

            {#if projectError}
              <div class="error">{projectError}</div>
            {/if}

            <button type="submit" disabled={projectLoading}>
              {projectLoading ? 'Starting...' : 'Start ReviewProject'}
            </button>
          </form>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .container {
    min-height: 100vh;
    padding: 20px;
  }

  .main-content {
    max-width: 800px;
    margin: 0 auto;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  .card {
    background: white;
    border-radius: 8px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    padding: 40px;
    width: 100%;
  }

  .landing-header h1 {
    margin-bottom: 12px;
  }

  .landing-explainer {
    margin: 0 0 14px 0;
    font-size: 14px;
    line-height: 1.55;
    color: #5a6c7d;
  }

  .landing-explainer p {
    margin: 0 0 12px 0;
  }

  .landing-explainer p:last-child {
    margin-bottom: 0;
  }

  .landing-explainer a {
    color: #2980b9;
    font-weight: 600;
    text-decoration: none;
  }

  .landing-explainer a:hover {
    text-decoration: underline;
  }

  .landing-lead {
    color: #7f8c8d;
    margin: 12px 0 12px 0;
    font-size: 15px;
    line-height: 1.45;
    font-weight: 600;
  }

  .start-project-footer {
    margin-top: 28px;
    padding-top: 24px;
    border-top: 1px solid #e0e4e8;
  }

  .start-project-caution {
    margin: 0 0 16px 0;
    padding: 14px 16px;
    font-size: 14px;
    line-height: 1.5;
    color: #4a5568;
    background: #f8f9fb;
    border: 1px solid #e6e9ee;
    border-radius: 6px;
  }

  .start-project-caution strong {
    display: block;
    margin-bottom: 8px;
    color: #2c3e50;
    font-size: 15px;
  }

  button.text-link-btn {
    width: auto;
    display: inline-block;
    padding: 0;
    margin: 0;
    background: none;
    border: none;
    border-radius: 0;
    color: #2980b9;
    font-size: 15px;
    font-weight: 600;
    text-decoration: underline;
    cursor: pointer;
    text-align: left;
  }

  button.text-link-btn:hover:not(:disabled) {
    background: none;
    color: #1f6391;
  }

  button.text-link-btn:disabled {
    background: none;
    color: #95a5a6;
  }

  .projects-primary {
    margin-top: 0;
  }

  .toggle-button-refresh {
    width: auto;
    min-width: 88px;
  }

  h1 {
    font-size: 28px;
    margin-bottom: 10px;
    color: #2c3e50;
  }

  .subtitle {
    color: #7f8c8d;
    margin-bottom: 30px;
    font-size: 16px;
  }

  .form-group {
    margin-bottom: 20px;
  }

  .context-toggle-button {
    width: 100%;
    padding: 10px 14px;
    border-radius: 8px;
    border: 1px solid #e0e4e8;
    background-color: #f8f9fa;
    cursor: pointer;
    text-align: left;
    transition:
      background-color 0.2s,
      border-color 0.2s;
  }

  .context-toggle-button:hover:enabled {
    background-color: #eef2f7;
    border-color: #d0d7de;
  }

  .context-toggle-button:disabled {
    opacity: 0.7;
    cursor: not-allowed;
  }

  .toggle-label {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 13px;
    color: #34495e;
  }

  .toggle-indicator {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    border: 2px solid #bdc3c7;
    background-color: white;
  }

  .toggle-indicator.on {
    border-color: #27ae60;
    background-color: #27ae60;
  }

  label {
    display: block;
    margin-bottom: 8px;
    font-weight: 500;
    color: #34495e;
  }

  .field-label {
    display: block;
    margin-bottom: 8px;
    font-weight: 500;
    color: #34495e;
  }

  .input-mode-row {
    display: flex;
    flex-wrap: wrap;
    gap: 16px 24px;
  }

  .input-mode-option {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    font-weight: 400;
    cursor: pointer;
  }

  .input-mode-option input {
    width: auto;
    margin: 0;
  }

  .geo-status {
    margin: 0 0 8px 0;
    color: #7f8c8d;
    font-size: 14px;
  }

  .error-inline {
    color: #c33;
  }

  button.secondary-btn {
    width: auto;
    display: inline-block;
    padding: 8px 14px;
    margin-top: 8px;
    background-color: #ecf0f1;
    color: #2c3e50;
  }

  button.secondary-btn:hover:not(:disabled) {
    background-color: #dfe6e9;
  }

  .geo-hint {
    margin: 10px 0 12px 0;
    font-size: 13px;
    color: #7f8c8d;
    line-height: 1.45;
  }

  .geo-hint code {
    font-size: 12px;
    background: #f4f6f8;
    padding: 2px 6px;
    border-radius: 4px;
  }

  .geo-collections-list {
    max-height: 220px;
    overflow-y: auto;
    border: 1px solid #e0e4e8;
    border-radius: 6px;
    padding: 8px 10px;
    background: #fafbfc;
  }

  .geo-check {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    margin: 0 0 8px 0;
    padding: 4px 0;
    font-weight: 400;
    cursor: pointer;
  }

  .geo-check:last-child {
    margin-bottom: 0;
  }

  .geo-check input {
    width: auto;
    margin-top: 3px;
    flex-shrink: 0;
  }

  .geo-check-label {
    flex: 1;
    min-width: 0;
    line-height: 1.35;
  }

  .geo-tag-id {
    flex-shrink: 0;
    font-size: 12px;
    color: #95a5a6;
    font-variant-numeric: tabular-nums;
  }

  input,
  select {
    width: 100%;
    padding: 12px;
    border: 1px solid #ddd;
    border-radius: 4px;
    font-size: 16px;
    transition: border-color 0.3s;
  }

  input:focus,
  select:focus {
    outline: none;
    border-color: #3498db;
  }

  input:disabled,
  select:disabled {
    background-color: #f5f5f5;
    cursor: not-allowed;
  }

  button {
    width: 100%;
    padding: 12px;
    background-color: #3498db;
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.3s;
  }

  button:hover:not(:disabled) {
    background-color: #2980b9;
  }

  button:disabled {
    background-color: #95a5a6;
    cursor: not-allowed;
  }

  .error {
    background-color: #fee;
    color: #c33;
    padding: 12px;
    border-radius: 4px;
    margin-bottom: 20px;
    border: 1px solid #fcc;
  }

  .project-divider {
    margin: 28px 0;
    border: 0;
    border-top: 1px solid #e0e4e8;
  }

  .projects-table-wrap {
    overflow-x: auto;
    margin-top: 12px;
  }

  .projects-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  .projects-table th,
  .projects-table td {
    border-bottom: 1px solid #e0e4e8;
    padding: 10px 8px;
    text-align: left;
    white-space: nowrap;
  }

  .projects-table th {
    color: #2c3e50;
    font-weight: 700;
    background: #f8f9fa;
  }

  .projects-name {
    max-width: 240px;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .projects-status {
    font-weight: 700;
    text-transform: lowercase;
    color: #34495e;
  }

  .projects-open {
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid #3498db;
    background-color: #3498db;
    color: white;
    font-weight: 700;
    cursor: pointer;
  }

  .projects-open:hover {
    background-color: #2980b9;
  }

  .project-section h2 {
    margin-bottom: 8px;
    color: #2c3e50;
    font-size: 20px;
  }

  .project-section .subtitle {
    margin: 0 0 18px 0;
    color: #7f8c8d;
    font-size: 14px;
  }

  .reviews-list h2 {
    font-size: 24px;
    margin-bottom: 20px;
    color: #2c3e50;
  }

  .reviews-list-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 20px;
  }

  .reviews-list-header h2 {
    margin-bottom: 0;
  }

  .toggle-button {
    padding: 8px 16px;
    background-color: #95a5a6;
    color: white;
    border: none;
    border-radius: 4px;
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
    transition: background-color 0.3s;
    white-space: nowrap;
  }

  .toggle-button:hover:not(:disabled) {
    background-color: #7f8c8d;
  }

  .toggle-button:disabled {
    background-color: #bdc3c7;
    cursor: not-allowed;
  }

  .empty-text {
    color: #7f8c8d;
    text-align: center;
    padding: 20px;
    font-style: italic;
  }

  .loading-text {
    color: #7f8c8d;
    text-align: center;
    padding: 20px;
  }

  .reviews-container {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .review-item {
    border: 1px solid #e0e0e0;
    border-radius: 6px;
    padding: 16px;
    cursor: pointer;
    transition: all 0.2s;
    background-color: #fafafa;
  }

  .review-item:hover {
    background-color: #f0f0f0;
    border-color: #3498db;
    box-shadow: 0 2px 8px rgba(52, 152, 219, 0.1);
  }

  .review-item.completed {
    background-color: #f8f9fa;
    border-color: #d5d5d5;
  }

  .review-item.completed:hover {
    background-color: #e9ecef;
    border-color: #95a5a6;
  }

  .review-item:focus {
    outline: 2px solid #3498db;
    outline-offset: 2px;
  }

  .review-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 8px;
  }

  .review-id {
    font-weight: 600;
    color: #2c3e50;
    font-size: 16px;
  }

  .completeness {
    font-weight: 600;
    color: #27ae60;
    font-size: 18px;
  }

  .completed-badge {
    color: #7f8c8d;
  }

  .review-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 14px;
    color: #7f8c8d;
  }

  .review-date {
    flex: 1;
  }

  .review-stats {
    margin-left: 16px;
  }
</style>
