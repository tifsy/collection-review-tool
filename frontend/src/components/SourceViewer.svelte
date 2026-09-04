<script>
  import iso3166 from "iso-3166-2";
  import * as rawIso3166 from "iso-3166";

  export let item;
  export let onKeep;
  export let onRemove;
  export let onSkip;
  export let editMetadata = false;
  export let showActions = true;
  export let onEditLanguage;
  export let onEditPubCountry;
  export let onEditPubState;
  export let loading = false;
  export let showSkip = true;
  export let showBackButton = false;
  export let onBack = null;
  export let backButtonTitle = "Back to recently reviewed source";
  export let showForwardButton = false;
  export let onForward = null;
  export let forwardButtonTitle = "Forward toward current queue item";
  export let decidedDecisionLabel = "";
  export let decidedModeMessage = "";
  export let showReturnToQueueButton = false;
  export let onReturnToQueue = null;

  let faviconUrl = null;
  let metadata = {};
  let correctLanguage = false;
  let correctPubCountry = false;
  let correctPubState = false;
  let lastItemId = null;

  function formatNumber(value) {
    if (value === null || value === undefined || isNaN(Number(value))) {
      return null;
    }
    return Number(value).toLocaleString("en-US");
  }

  function formatDateTime(value) {
    if (!value) return null;
    const date = new Date(value);
    if (isNaN(date.getTime())) return null;
    return date.toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }

  /**
   * MediaCloud directory list API uses SourcesViewSerializer: last_story is DateTimeField(format="%m/%Y")
   * (e.g. "3/2024"), which `new Date()` cannot parse. Single-source responses may use ISO strings instead.
   */
  function formatLastStory(value) {
    if (value === null || value === undefined || value === "") return null;
    if (typeof value === "string") {
      const trimmed = value.trim();
      const m = trimmed.match(/^(\d{1,2})\/(\d{4})$/);
      if (m) {
        const monthIndex = parseInt(m[1], 10) - 1;
        const year = parseInt(m[2], 10);
        if (monthIndex >= 0 && monthIndex <= 11 && Number.isFinite(year) && year > 0) {
          const date = new Date(year, monthIndex, 1);
          return date.toLocaleDateString("en-US", { year: "numeric", month: "short" });
        }
      }
    }
    return formatDateTime(value);
  }

  /** MediaCloud Source Directory fields (web-search sources.models.Source): stories_total, last_story, stories_per_week */
  function pickNumericMeta(meta, snake, camel) {
    const raw = meta[snake] ?? meta[camel];
    if (raw === null || raw === undefined || raw === "") return null;
    const n = Number(raw);
    return Number.isFinite(n) ? n : null;
  }

  function formatPubState(pubState, pubCountry) {
    if (!pubState) return "—";

    const normalizedState = String(pubState).trim().toUpperCase();
    const subdivision = iso3166.subdivision(normalizedState);
    if (!subdivision) return normalizedState;

    if (pubCountry) {
      const normalizedCountry = String(pubCountry).trim().toUpperCase();
      const alpha2Country =
        normalizedCountry.length === 3
          ? rawIso3166.iso31661Alpha3ToAlpha2[normalizedCountry] || normalizedCountry
          : normalizedCountry;
      if (subdivision.countryCode && subdivision.countryCode !== alpha2Country) {
        return normalizedState;
      }
    }

    return `${normalizedState} – ${subdivision.name}`;
  }

  function formatPubCountry(pubCountry) {
    if (!pubCountry) return "—";
    const normalizedCountry = String(pubCountry).trim().toUpperCase();
    const alpha2Country =
      normalizedCountry.length === 3
        ? rawIso3166.iso31661Alpha3ToAlpha2[normalizedCountry] || normalizedCountry
        : normalizedCountry;
    const countryName = iso3166.data[alpha2Country]?.name;
    return countryName ? `${normalizedCountry} – ${countryName}` : normalizedCountry;
  }

  $: metadata = item && item.source_metadata ? item.source_metadata : {};

  $: storiesTotalApprox = pickNumericMeta(metadata, "stories_total", "storiesTotal");
  $: storiesTotalLabel =
    storiesTotalApprox !== null ? formatNumber(storiesTotalApprox) : null;

  $: lastStoryRaw = metadata.last_story ?? metadata.lastStory;
  $: lastStoryLabel = formatLastStory(lastStoryRaw);

  $: storiesPerWeekVal = pickNumericMeta(metadata, "stories_per_week", "storiesPerWeek");
  $: isActivelyIndexing = storiesPerWeekVal !== null && storiesPerWeekVal > 0;
  $: directoryStatLede = storiesTotalLabel
    ? `~${storiesTotalLabel} stories in Media Cloud, ${
        isActivelyIndexing ? "actively indexing" : "not actively indexing"
      }`
    : "Source directory stats unavailable";
  $: pubStateLabel = formatPubState(metadata.pub_state, metadata.pub_country);
  $: pubCountryLabel = formatPubCountry(metadata.pub_country);

  $: showDirectoryStats =
    item && !item.is_new_source && item.source_id;

  $: if (item && item.source_homepage) {
    try {
      faviconUrl = `https://www.google.com/s2/favicons?domain_url=${encodeURIComponent(
        item.source_homepage
      )}&sz=64`;
    } catch (e) {
      faviconUrl = null;
    }
  } else {
    faviconUrl = null;
  }

  // Reset "correct" flags when the review item changes
  $: if (item && item.id !== lastItemId) {
    lastItemId = item.id;
    correctLanguage = false;
    correctPubCountry = false;
    correctPubState = false;
  }

  function handleEditLanguage() {
    correctLanguage = true;
    if (onEditLanguage) onEditLanguage();
  }

  function handleEditPubCountry() {
    correctPubCountry = true;
    if (onEditPubCountry) onEditPubCountry();
  }

  function handleEditPubState() {
    correctPubState = true;
    if (onEditPubState) onEditPubState();
  }

  $: canKeep = !loading && (!editMetadata || (correctLanguage && correctPubCountry && correctPubState));
  $: decidedDecisionClass =
    decidedDecisionLabel === "keep"
      ? "decision-keep"
      : decidedDecisionLabel === "remove"
      ? "decision-remove"
      : decidedDecisionLabel === "add"
      ? "decision-add"
      : decidedDecisionLabel === "skip"
      ? "decision-skip"
      : "";
</script>

{#if item}
  <div class="source-viewer">
    {#if showBackButton}
      <button
        type="button"
        class="review-back-button"
        on:click={onBack}
        title={backButtonTitle}
        aria-label={backButtonTitle}
      >
        ←
      </button>
    {/if}
    {#if showForwardButton}
      <button
        type="button"
        class="review-forward-button"
        on:click={onForward}
        title={forwardButtonTitle}
        aria-label={forwardButtonTitle}
      >
        →
      </button>
    {/if}
    {#if decidedModeMessage || decidedDecisionLabel || showReturnToQueueButton}
      <div class="decided-mode-center">
        {#if decidedModeMessage}
          <div class="decided-mode-chip decided-mode-message">{decidedModeMessage}</div>
        {/if}
        {#if decidedDecisionLabel}
          <div class={`decided-mode-chip decided-decision-pill ${decidedDecisionClass}`}>
            Previous decision: {decidedDecisionLabel}
          </div>
        {/if}
        {#if showReturnToQueueButton}
          <button
            type="button"
            class="decided-mode-chip return-to-queue-button"
            on:click={onReturnToQueue}
          >
            Back to undecided queue →
          </button>
        {/if}
      </div>
    {/if}
    <div class="source-info">
      <div class="source-header">
        <div class="source-title-row">
          {#if faviconUrl}
            <img src={faviconUrl} alt="" class="favicon" />
          {/if}
          <div class="title-and-url">
            <h3>{item.source_label || 'Unnamed Source'}</h3>
            {#if item.source_homepage}
              <a
                href={item.source_homepage}
                target="_blank"
                rel="noopener noreferrer"
                class="homepage-inline"
              >
                {item.source_homepage}
              </a>
            {/if}
          </div>
        </div>
        <div class="header-right">
          {#if !item.is_new_source && item.source_id}
            <a 
              href={`https://search.mediacloud.org/sources/${item.source_id}`}
              target="_blank"
              rel="noopener noreferrer"
              class="mediacloud-link"
              title="Review source in MediaCloud"
            >
              Review in MediaCloud ↗
            </a>
          {/if}
        </div>
      </div>
      {#if item.is_new_source}
        <span class="badge new-source">New Source</span>
      {/if}

      {#if item.skip_note}
        <div class="skip-note-callout" role="note">
          <div class="skip-note-label">Skip note</div>
          <div class="skip-note-text">{item.skip_note}</div>
        </div>
      {/if}

      {#if showDirectoryStats}
        <div class="directory-stats" aria-label="Source Directory">
          <p class="directory-stats-lede" title="Source Directory context: total stories, last seen date, and recent weekly volume">
            {directoryStatLede}
          </p>
        </div>
      {/if}

      {#if (item.source_id) || (item.is_new_source && (editMetadata || metadata.primary_language || metadata.language || metadata.pub_country || metadata.pub_state))}
        <div class="source-metadata">
          <div class="metadata-grid">
            <div class="meta-card">
              <div class="meta-label">Language</div>
              <div class="meta-row">
                <div class="meta-value">
                  {metadata.primary_language || metadata.language || '—'}
                </div>
                {#if editMetadata}
                  <div class="meta-controls">
                    <button type="button" class="meta-correct-button">
                      <label class="meta-checkbox-label">
                        <input type="checkbox" bind:checked={correctLanguage} />
                        <span>Correct</span>
                      </label>
                    </button>
                    <button type="button" class="meta-edit-button" on:click={handleEditLanguage}>
                      Edit
                    </button>
                  </div>
                {/if}
              </div>
            </div>
            <div class="meta-card">
              <div class="meta-label">Pub country</div>
              <div class="meta-row">
                <div class="meta-value">
                  {pubCountryLabel}
                </div>
                {#if editMetadata}
                  <div class="meta-controls">
                    <button type="button" class="meta-correct-button">
                      <label class="meta-checkbox-label">
                        <input type="checkbox" bind:checked={correctPubCountry} />
                        <span>Correct</span>
                      </label>
                    </button>
                    <button type="button" class="meta-edit-button" on:click={handleEditPubCountry}>
                      Edit
                    </button>
                  </div>
                {/if}
              </div>
            </div>
            <div class="meta-card">
              <div class="meta-label">Pub state</div>
              <div class="meta-row">
                <div class="meta-value">
                  {pubStateLabel}
                </div>
                {#if editMetadata}
                  <div class="meta-controls">
                    <button type="button" class="meta-correct-button">
                      <label class="meta-checkbox-label">
                        <input type="checkbox" bind:checked={correctPubState} />
                        <span>Correct</span>
                      </label>
                    </button>
                    <button type="button" class="meta-edit-button" on:click={handleEditPubState}>
                      Edit
                    </button>
                  </div>
                {/if}
              </div>
            </div>
          </div>
        </div>
      {/if}
    </div>
    
    {#if showActions}
      <div class="actions">
        <div class="actions-left">
          <button 
            class="btn btn-remove" 
            on:click={onRemove} 
            disabled={loading}
          >
            Remove
          </button>
        </div>
        <div class="actions-right">
          {#if showSkip}
            <button
              class="btn btn-skip"
              on:click={onSkip}
              disabled={loading}
            >
              Skip for now
            </button>
          {/if}
          <button 
            class="btn btn-keep" 
            on:click={onKeep} 
            disabled={!canKeep}
            title={!canKeep && editMetadata
              ? 'To keep this source, first mark Language, Pub country, and Pub state as correct.'
              : undefined}
          >
            Keep
          </button>
        </div>
      </div>
    {/if}
  </div>
{:else}
  <div class="no-items">
    <p>No more items to review!</p>
  </div>
{/if}

<style>
  .source-viewer {
    position: relative;
    background: white;
    padding: 30px;
    border-radius: 8px;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
    margin: 0 auto 20px;
    width: 80%;
  }

  .review-back-button {
    position: absolute;
    top: auto;
    bottom: -40px;
    left: -16px;
    width: 32px;
    height: 32px;
    border-radius: 999px;
    border: 1px solid #cfd8e3;
    background: #ffffff;
    color: #2c3e50;
    font-size: 18px;
    font-weight: 700;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
    transition: background-color 0.2s, border-color 0.2s, transform 0.1s;
  }

  .review-back-button:hover {
    background: #f6f8fa;
    border-color: #b8c2cc;
  }

  .review-back-button:active {
    transform: translateY(1px);
  }

  .review-forward-button {
    position: absolute;
    top: auto;
    bottom: -40px;
    right: -16px;
    width: 32px;
    height: 32px;
    border-radius: 999px;
    border: 1px solid #cfd8e3;
    background: #ffffff;
    color: #2c3e50;
    font-size: 18px;
    font-weight: 700;
    line-height: 1;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
    transition: background-color 0.2s, border-color 0.2s, transform 0.1s;
  }

  .review-forward-button:hover {
    background: #f6f8fa;
    border-color: #b8c2cc;
  }

  .review-forward-button:active {
    transform: translateY(1px);
  }

  .decided-mode-chip {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 28px;
    padding: 4px 10px;
    border-radius: 999px;
    font-size: 12px;
    line-height: 1.2;
    font-weight: 700;
    white-space: nowrap;
  }

  .decided-decision-pill {
    border: 1px solid #d0d7de;
    background: #f6f8fa;
    color: #34495e;
    text-transform: capitalize;
  }

  .decided-decision-pill.decision-keep {
    background-color: #d4edda;
    border-color: #badbcc;
    color: #155724;
  }

  .decided-decision-pill.decision-remove {
    background-color: #f8d7da;
    border-color: #f5c2c7;
    color: #721c24;
  }

  .decided-decision-pill.decision-add {
    background-color: #d1ecf1;
    border-color: #bcdfe6;
    color: #0c5460;
  }

  .decided-decision-pill.decision-skip {
    background-color: #e2e3e5;
    border-color: #d3d6d8;
    color: #495057;
  }

  .decided-mode-center {
    position: absolute;
    left: 50%;
    bottom: -48px;
    transform: translateX(-50%);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    max-width: calc(100% - 112px);
  }

  .decided-mode-message {
    border: 1px solid #cfe2ff;
    background: #f5faff;
    color: #2c3e50;
    font-weight: 700;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .return-to-queue-button {
    border: 1px solid #cfe2ff;
    background: #f5faff;
    color: #2c3e50;
    cursor: pointer;
    transition: background-color 0.2s, border-color 0.2s;
  }

  .return-to-queue-button:hover {
    background: #e9f4ff;
    border-color: #b7d6ff;
  }

  .source-info {
    margin-bottom: 25px;
  }

  .source-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 15px;
    margin-bottom: 10px;
    flex-wrap: wrap;
  }

  .header-right {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
  }

  .source-title-row {
    display: flex;
    align-items: stretch;
    gap: 12px;
  }

  .title-and-url {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
    flex: 1;
  }

  h3 {
    font-size: 22px;
    margin: 0;
    color: #2c3e50;
    flex: 0 0 auto;
  }

  .favicon {
    width: 40px;
    height: 40px;
    border-radius: 4px;
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.06);
    flex-shrink: 0;
  }

  .mediacloud-link {
    color: #3498db;
    text-decoration: none;
    font-size: 14px;
    white-space: nowrap;
    transition: color 0.3s;
  }

  .directory-stats {
    margin-top: 10px;
    margin-bottom: 4px;
  }

  .directory-stats-lede {
    margin: 0;
    font-size: 12px;
    line-height: 1.4;
    color: #7f8c8d;
    font-variant-numeric: tabular-nums;
  }

  .mediacloud-link:hover {
    color: #2980b9;
    text-decoration: underline;
  }

  .source-metadata {
    margin-top: 16px;
    padding-top: 16px;
    border-top: 1px solid #ecf0f1;
  }

  .metadata-grid {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
  }

  .meta-card {
    background: #f8f9fa;
    border-radius: 10px;
    padding: 12px 14px;
    border: 1px solid #e0e4e8;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }

  .meta-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }

  .meta-label {
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    color: #7f8c8d;
    font-weight: 600;
  }

  .meta-value {
    font-size: 15px;
    color: #2c3e50;
    word-break: break-word;
  }

  .meta-controls {
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .meta-checkbox-label {
    display: flex;
    align-items: center;
    gap: 4px;
    font-size: 12px;
    color: #34495e;
  }

  .meta-checkbox-label input {
    width: 14px;
    height: 14px;
  }

  .meta-correct-button {
    padding: 4px 8px;
    border-radius: 999px;
    border: 1px solid #d0d7de;
    background-color: #f8f9fa;
    cursor: pointer;
    transition: background-color 0.2s, border-color 0.2s;
  }

  .meta-correct-button:hover {
    background-color: #e1e4e8;
    border-color: #c0c7d0;
  }

  .meta-edit-button {
    padding: 4px 8px;
    border-radius: 999px;
    border: 1px solid #d0d7de;
    background-color: white;
    font-size: 12px;
    font-weight: 500;
    color: #34495e;
    cursor: pointer;
    transition: background-color 0.2s, border-color 0.2s;
  }

  .meta-edit-button:hover {
    background-color: #f6f8fa;
    border-color: #c0c7d0;
  }

  .monospace {
    font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  }

  .homepage-inline {
    color: #3498db;
    text-decoration: none;
    font-size: 14px;
    word-break: break-all;
  }

  .homepage-inline:hover {
    text-decoration: underline;
  }

  .badge {
    display: inline-block;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 500;
    margin-top: 10px;
  }

  .new-source {
    background-color: #3498db;
    color: white;
  }

  .skip-note-callout {
    margin-top: 14px;
    padding: 12px 14px;
    border-radius: 8px;
    border: 1px solid #e6d9a8;
    background: #fffbf0;
  }

  .skip-note-label {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    color: #856404;
    margin-bottom: 6px;
  }

  .skip-note-text {
    font-size: 14px;
    line-height: 1.45;
    color: #4a3f20;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .actions {
    display: flex;
    justify-content: space-between;
    gap: 12px;
  }

  .actions-left,
  .actions-right {
    display: flex;
    gap: 12px;
    flex: 1;
  }

  .actions-left {
    justify-content: flex-start;
  }

  .actions-right {
    justify-content: flex-end;
  }

  .btn {
    padding: 14px 24px;
    border: none;
    border-radius: 6px;
    font-size: 16px;
    font-weight: 500;
    cursor: pointer;
    transition: all 0.3s;
  }

  .btn:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .btn-keep {
    min-width: 50%;
    background-color: #27ae60;
    color: white;
  }

  .btn-keep:hover:not(:disabled) {
    background-color: #229954;
  }

  .btn-remove {
    min-width: 50%;
    background-color: transparent;
    color: #e74c3c;
    border: 1px solid #e74c3c;
  }

  .btn-remove:hover:not(:disabled) {
    background-color: rgba(231, 76, 60, 0.08);
  }

  .btn-skip {
    flex: 0 0 20%;
    background-color: #fff3cd;
    color: #856404;
  }

  .btn-skip:hover:not(:disabled) {
    background-color: #ffe08a;
  }

  .no-items {
    background: white;
    padding: 40px;
    border-radius: 8px;
    text-align: center;
    box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
  }

  .no-items p {
    font-size: 18px;
    color: #7f8c8d;
  }
</style>
