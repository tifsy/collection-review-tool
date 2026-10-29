<script>
  import DOMPurify from 'dompurify';
  import { marked } from 'marked';
  import { onMount } from 'svelte';

  import {
    decideQueueItem,
    getReviewByQueueGuid,
    getReviewItemsByQueueGuid,
    getReviewQueueGuidelines,
    proposeNewSourceByQueueGuid,
    updateQueueItemSourceMetadata,
  } from '../../lib/api.js';
  import Nav from './Nav.svelte';

  export let onNavigate = () => {};
  export let navVariant = 'glass';

  // Queue GUID from /demo/reviews/{queueGuid}
  const queueGuid = window.location.pathname.split('/').pop();

  let projectGuid = '';
  let projectName = '';
  let items = [];
  let sourceIdx = 0;
  let loading = true;
  let loadError = '';
  let saving = false;
  let guidelines = '';
  $: guidelinesHtml = DOMPurify.sanitize(marked.parse(guidelines, { async: false }), {
    USE_PROFILES: { html: true },
    FORBID_TAGS: ['style'],
    FORBID_ATTR: ['style'],
  });
  let guidelinesLoading = true;
  let guidelinesError = '';

  function adaptItem(item) {
    const metadata = item.source_metadata ?? {};

    return {
      ...item,
      title: item.source_label || `Source ${item.source_id ?? item.id}`,
      homepage: item.source_homepage || '',
      language: metadata.primary_language || '—',
      country: metadata.pub_country || '—',
      state: metadata.pub_state || '—',
    };
  }

  onMount(async () => {
    getReviewQueueGuidelines(queueGuid)
      .then((result) => {
        guidelines = result || '';
      })
      .catch((error) => {
        console.error(error);

        guidelinesError =
          error.response?.data?.error || error.message || 'Could not load guidelines.';
      })
      .finally(() => {
        guidelinesLoading = false;
      });

    try {
      const [queueData, itemData] = await Promise.all([
        getReviewByQueueGuid(queueGuid),
        getReviewItemsByQueueGuid(queueGuid, {
          page: 1,
          page_size: 1000,
        }),
      ]);

      projectGuid = queueData.review_project_guid || '';
      projectName = queueData.name || queueData.collection_name || 'Review project';

      items = (itemData.items || []).map(adaptItem);

      const firstUndecided = items.findIndex((item) => item.decision === 'undecided');

      sourceIdx = firstUndecided >= 0 ? firstUndecided : Math.max(0, items.length - 1);
    } catch (error) {
      console.error(error);

      loadError = error.response?.data?.error || error.message || 'Could not load this queue.';
    } finally {
      loading = false;
    }
  });

  $: src = items[sourceIdx] ?? null;

  $: allDone = !loading && items.length > 0 && items.every((item) => item.decision !== 'undecided');

  $: currentDecision =
    src && src.decision !== 'undecided'
      ? {
          verdict: {
            keep: 'kept',
            remove: 'removed',
            add: 'added',
            skip: 'skipped',
          }[src.decision],
          reason: src.removal_reason || src.skip_note || '',
        }
      : null;

  $: meta = src
    ? [
        {
          k: 'primary_language',
          label: 'Language',
          v: src.language,
        },
        {
          k: 'pub_country',
          label: 'Pub country',
          v: src.country,
        },
        {
          k: 'pub_state',
          label: 'Pub state',
          v: src.state,
        },
      ]
    : [];

  $: counts = {
    totalKept: items.filter((item) => item.decision === 'keep').length,

    totalRemoved: items.filter((item) => item.decision === 'remove').length,

    totalSkipped: items.filter((item) => item.decision === 'skip').length,

    totalAdded: items.filter((item) => item.decision === 'add').length,

    totalDecided: items.filter((item) => item.decision !== 'undecided').length,
  };

  function navigateToSource(index) {
    sourceIdx = Math.max(0, Math.min(index, items.length - 1));
  }

  function replaceItem(updatedItem) {
    items = items.map((item) => (item.id === updatedItem.id ? adaptItem(updatedItem) : item));
  }

  $: sourceHref = src?.homepage
    ? /^https?:\/\//i.test(src.homepage)
      ? src.homepage
      : `https://${src.homepage}`
    : '#';

  // ── Metadata editing ──────────────────────────────────────────────────────
  let editingField = null;
  let editVal = '';

  function startEdit(field) {
    editingField = field.k;
    editVal = field.v;
  }

  async function saveEdit() {
    if (!src || !editingField || saving) return;

    try {
      saving = true;

      const data = await updateQueueItemSourceMetadata(queueGuid, src.id, {
        [editingField]: editVal,
      });

      replaceItem(data.item);
      editingField = null;
    } catch (error) {
      console.error(error);

      loadError = error.response?.data?.error || error.message || 'Could not update metadata.';
    } finally {
      saving = false;
    }
  }

  function cancelEdit() {
    editingField = null;
  }

  let confirmedFields = {};

  $: if (sourceIdx || sourceIdx === 0) {
    editingField = null;
    confirmedFields = {};
  }

  function toggleConfirm(k) {
    confirmedFields = { ...confirmedFields, [k]: !confirmedFields[k] };
  }

  $: isConfirmed = (k) => confirmedFields[k] ?? k !== 'pub_state';

  // ── Reason modal (Fix 5) ─────────────────────────────────────────────────
  // Keep and Remove require a reason before committing.
  let reasonModal = null; // { pendingVerdict: 'keep' | 'remove' }
  let reasonText = '';
  $: reasonVerbLabel = reasonModal?.pendingVerdict === 'keep' ? 'Keep' : 'Remove';
  $: reasonCanConfirm = reasonText.trim().length > 0;

  function openReasonModal(verdict) {
    reasonModal = { pendingVerdict: verdict };
    reasonText = currentDecision?.reason ?? '';
  }

  function cancelReason() {
    reasonModal = null;
    reasonText = '';
  }

  async function confirmReason() {
    if (!reasonCanConfirm || !src || saving) return;

    const reason = reasonText.trim();
    const decision = reasonModal.pendingVerdict;

    try {
      saving = true;

      const updatedItem = await decideQueueItem(
        queueGuid,
        src.id,
        decision,
        decision === 'remove' ? reason : null
      );

      replaceItem(updatedItem);

      if (sourceIdx < items.length - 1) {
        sourceIdx += 1;
      }

      reasonModal = null;
      reasonText = '';
    } catch (error) {
      console.error(error);

      loadError = error.response?.data?.error || error.message || 'Could not save the decision.';
    } finally {
      saving = false;
    }
  }

  // ── Decisions ─────────────────────────────────────────────────────────────
  // Keep/Remove open reason modal; Skip is immediate.
  async function keep() {
    if (!src || saving) return;

    try {
      saving = true;

      const updatedItem = await decideQueueItem(queueGuid, src.id, 'keep');

      replaceItem(updatedItem);

      if (sourceIdx < items.length - 1) {
        sourceIdx += 1;
      }
    } catch (error) {
      console.error(error);

      loadError = error.response?.data?.error || error.message || 'Could not save the decision.';
    } finally {
      saving = false;
    }
  }

  function remove() {
    openReasonModal('remove');
  }

  async function skip() {
    if (!src || saving) return;

    try {
      saving = true;

      const updatedItem = await decideQueueItem(queueGuid, src.id, 'skip');

      replaceItem(updatedItem);

      if (sourceIdx < items.length - 1) {
        sourceIdx += 1;
      }
    } catch (error) {
      console.error(error);

      loadError = error.response?.data?.error || error.message || 'Could not save the decision.';
    } finally {
      saving = false;
    }
  }

  // Keyboard shortcuts
  function onKey(e) {
    if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
      return;
    }

    if (allDone || reasonModal || saving) {
      return;
    }

    if (e.key === 'k' || e.key === 'Enter') {
      keep();
    }

    if (e.key === 'r') {
      remove();
    }

    if (e.key === 's') {
      skip();
    }

    if (e.key === 'ArrowLeft' && sourceIdx > 0) {
      navigateToSource(sourceIdx - 1);
    }

    if (e.key === 'ArrowRight' && sourceIdx < items.length - 1) {
      navigateToSource(sourceIdx + 1);
    }
  }

  // ── Propose-new-source modal ──────────────────────────────────────────────
  let showPropose = false;
  let proposeLabel = '';
  let proposeUrl = '';
  let proposeToast = '';

  async function submitPropose() {
    if (!proposeLabel.trim() || !proposeUrl.trim() || saving) {
      return;
    }

    try {
      saving = true;

      const createdItem = await proposeNewSourceByQueueGuid(
        queueGuid,
        proposeLabel.trim(),
        proposeUrl.trim()
      );

      items = [...items, adaptItem(createdItem)];

      proposeLabel = '';
      proposeUrl = '';
      showPropose = false;
      proposeToast = 'Source added — it appears in Added.';

      setTimeout(() => {
        proposeToast = '';
      }, 2500);
    } catch (error) {
      console.error(error);

      loadError = error.response?.data?.error || error.message || 'Could not add the source.';
    } finally {
      saving = false;
    }
  }
</script>

<svelte:window on:keydown={onKey} />

<div class="review-page">
  <Nav
    role="queue"
    projectCtx={projectName}
    {projectGuid}
    {queueGuid}
    {onNavigate}
    variant={navVariant}
  />

  <!-- ── ALL-DONE STATE ─────────────────────────────────────────────────── -->
  {#if loading}
    <div class="done-wrap">
      <div class="done-card">Loading review queue...</div>
    </div>
  {:else if loadError}
    <div class="done-wrap">
      <div class="done-card">
        {loadError}
      </div>
    </div>
  {:else if items.length === 0}
    <div class="done-wrap">
      <div class="done-card">This queue has no sources.</div>
    </div>
  {:else if allDone}
    <div class="done-wrap">
      <div class="done-card">
        <div class="done-icon">
          <svg
            width="22"
            height="22"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"><path d="M5 12.5 10 17.5l9-11" /></svg
          >
        </div>
        <h2 class="done-h2">Queue complete</h2>
        <p class="done-sub">You've reviewed all {items.length} sources in this demo session.</p>
        <div class="done-tally">
          {#each [{ l: 'Kept', n: counts.totalKept, c: 'var(--v2-kept)' }, { l: 'Removed', n: counts.totalRemoved, c: 'var(--v2-removed)' }, { l: 'Skipped', n: counts.totalSkipped, c: 'var(--v2-skipped)' }, { l: 'Added', n: counts.totalAdded, c: 'var(--v2-added)' }] as t}
            <div class="done-stat">
              <span class="done-dot" style:background={t.c}></span>
              <span class="done-n" style:color={t.c}>{t.n}</span>
              <span class="done-l">{t.l}</span>
            </div>
          {/each}
        </div>
        <!-- Fix 2: primary = Back to review at last source; secondary = decisions page -->
        <div class="done-actions">
          <button
            class="btn btn-primary"
            on:click={() => {
              navigateToSource(items.length - 1);
            }}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
              stroke-linejoin="round"
              style="transform:rotate(180deg)"><path d="M5 12h14M13 6l6 6-6 6" /></svg
            >
            Back to review
          </button>
          <button
            class="btn"
            on:click={() =>
              onNavigate(`/demo/review-projects/${projectGuid}/queues/${queueGuid}/decisions`)}
          >
            <svg
              width="13"
              height="13"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              ><path d="M12 3 2 8l10 5 10-5z" /><path d="m2 14 10 5 10-5M2 11l10 5 10-5" /></svg
            >
            Check all decisions
          </button>
        </div>
      </div>
    </div>
  {:else}
    <!-- ── ACTION BAR ──────────────────────────────────────────────────── -->
    <div class="action-bar-wrap">
      <div class="action-bar">
        <button
          class="btn btn-sm"
          on:click={() => onNavigate(`/demo/review-projects/${projectGuid}/queues/${queueGuid}`)}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
            style="transform:rotate(180deg)"><path d="M5 12h14M13 6l6 6-6 6" /></svg
          >
          Back to queue
        </button>
        <div class="action-divider"></div>

        <div class="progress-pill">
          <span class="progress-current">{sourceIdx + 1}</span>
          <span class="progress-sep">/ {items.length}</span>
          <div class="progress-mini-track">
            <div
              class="progress-mini-fill"
              style:width="{Math.round(((sourceIdx + 1) / items.length) * 100)}%"
            ></div>
          </div>
          <span class="progress-pct-label"
            >{Math.round(((sourceIdx + 1) / items.length) * 100)}%</span
          >
        </div>

        <div class="action-spacer"></div>

        <button
          class="btn btn-sm"
          on:click={() =>
            onNavigate(`/demo/review-projects/${projectGuid}/queues/${queueGuid}/decisions`)}
        >
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            ><path d="M12 3 2 8l10 5 10-5z" /><path d="m2 14 10 5 10-5M2 11l10 5 10-5" /></svg
          >
          All decisions · {counts.totalDecided}
        </button>
        <button class="btn btn-primary btn-sm" on:click={() => (showPropose = true)}>
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
            stroke-linecap="round"><path d="M12 5v14M5 12h14" /></svg
          >
          Propose new source
        </button>
      </div>
    </div>

    <!-- ── TWO-COLUMN LAYOUT ───────────────────────────────────────────── -->
    <div class="main-grid">
      <!-- Source card -->
      <div class="card">
        <!-- Source header -->
        <div class="source-header">
          <div class="source-header-row">
            <div class="source-header-left">
              <h1 class="source-title">{src.title}</h1>
              {#if currentDecision}
                {@const VCOLORS = {
                  kept: 'var(--v2-kept)',
                  removed: 'var(--v2-removed)',
                  added: 'var(--v2-added)',
                  skipped: 'var(--v2-skipped)',
                }}
                {@const VLABELS = {
                  kept: 'Kept',
                  removed: 'Removed',
                  added: 'Added',
                  skipped: 'Skipped',
                }}
                <div class="chips-row">
                  <span
                    class="chip chip-decided"
                    style:background={`var(--v2-${currentDecision.verdict}-soft)`}
                    style:color={VCOLORS[currentDecision.verdict]}
                  >
                    <span class="chip-dot" style:background={VCOLORS[currentDecision.verdict]}
                    ></span>
                    {VLABELS[currentDecision.verdict]}
                  </span>
                </div>
              {/if}
              <div class="source-links">
                <span class="source-link-static">
                  <svg
                    width="14"
                    height="14"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                    ><circle cx="12" cy="12" r="9" /><path
                      d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"
                    /></svg
                  >
                  {src.homepage}
                </span>
                <a class="source-link" href={sourceHref} target="_blank" rel="noreferrer">
                  Review in Media Cloud
                  <svg
                    width="12"
                    height="12"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.6"
                    stroke-linecap="round"
                    stroke-linejoin="round"><path d="M7 17 17 7M9 7h8v8" /></svg
                  >
                </a>
              </div>
              {#if currentDecision?.reason}
                <div class="prev-reason">Previous note: "{currentDecision.reason}"</div>
              {/if}
            </div>
            <div class="source-nav">
              <button
                class="nav-circle"
                disabled={sourceIdx === 0}
                on:click={() => navigateToSource(sourceIdx - 1)}
                aria-label="Previous source"
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"><path d="M15 18l-6-6 6-6" /></svg
                >
              </button>

              <button
                class="nav-circle"
                disabled={sourceIdx >= items.length - 1}
                on:click={() => navigateToSource(sourceIdx + 1)}
                aria-label="Next source"
              >
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  stroke-width="1.8"
                  stroke-linecap="round"
                  stroke-linejoin="round"><path d="M9 18l6-6-6-6" /></svg
                >
              </button>
            </div>
          </div>
        </div>

        <!-- AI reviewer's call (projects imported from the AI reviewer) -->
        {#if src.ai}
          {@const ai = src.ai}
          {@const evidence = ai.evidence ?? {}}
          <div class="ai-box" role="note" aria-label="AI reviewer">
            <div class="ai-box-label">
              AI reviewer ·
              {#if ai.decision === 'undecided'}
                left for you{ai.proposal ? ` (leans ${ai.proposal})` : ''}
              {:else}
                {ai.decision}
              {/if}
              {#if ai.decided_by}<span class="ai-box-by">· {ai.decided_by}</span>{/if}
            </div>
            {#if ai.why_human}
              <div class="ai-box-text"><b>Why you:</b> {ai.why_human}</div>
            {/if}
            {#if ai.reason && ai.reason !== ai.why_human}
              <div class="ai-box-text">{ai.reason}</div>
            {/if}
            {#if evidence.mc_status}
              <div class="ai-box-evidence">
                Media Cloud: {evidence.mc_status}, {evidence.d90 || 0} stories in 90 days,
                {evidence.stories_total || 0} in total{evidence.last_story
                  ? `, last ${evidence.last_story}`
                  : ''}
              </div>
            {/if}
            {#if src.decision !== 'undecided' && !src.decided_at}
              <div class="ai-box-evidence">
                The decision above is the AI's. Confirm it or change it to record your own.
              </div>
            {/if}
          </div>
        {/if}

        <!-- Metadata section -->
        <div class="meta-heading-row">
          <span class="meta-heading">Source metadata</span>
          <span class="meta-hint">Confirm each field, or click Edit to fix.</span>
        </div>
        <div class="meta-grid">
          {#each meta as field, i}
            <div class="meta-cell" class:has-right-border={i < 2}>
              <div class="meta-label">{field.label}</div>

              {#if editingField === field.k}
                <input
                  class="meta-edit-input"
                  bind:value={editVal}
                  on:keydown={(e) => e.key === 'Enter' && saveEdit()}
                />
                <div class="meta-edit-actions">
                  <button class="btn btn-sm btn-accent" on:click={saveEdit}>Save</button>
                  <button class="btn btn-sm" on:click={cancelEdit}>Cancel</button>
                </div>
              {:else}
                <div class="meta-value">{field.v}</div>
                <div class="meta-actions">
                  <button
                    class="correct-label"
                    class:correct-yes={isConfirmed(field.k)}
                    on:click={() => toggleConfirm(field.k)}
                  >
                    <span class="checkbox" class:checked={isConfirmed(field.k)}>
                      {#if isConfirmed(field.k)}
                        <svg
                          width="10"
                          height="10"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="#fff"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"><path d="M5 12.5 10 17.5l9-11" /></svg
                        >
                      {/if}
                    </span>
                    Correct
                  </button>
                  <button class="btn btn-sm" on:click={() => startEdit(field)}>Edit</button>
                </div>
              {/if}
            </div>
          {/each}
        </div>
        <div class="meta-local-note">
          <svg
            width="12"
            height="12"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
            stroke-linecap="round"
            stroke-linejoin="round"
            ><circle cx="12" cy="12" r="9" /><path d="M12 8v4M12 16h.01" /></svg
          >
          "Correct" is a session-only toggle. "Edit" saves metadata changes to the backend when metadata
          editing is enabled.
        </div>

        <!-- Decision dock -->
        <div class="decision-dock">
          <span class="dock-label">Decide</span>
          <button
            class="dock-btn dock-remove"
            class:dock-active-remove={currentDecision?.verdict === 'removed'}
            on:click={remove}
          >
            Remove
            <kbd class="kbd">R</kbd>
          </button>
          <button
            class="dock-btn dock-skip"
            class:dock-active-skip={currentDecision?.verdict === 'skipped'}
            on:click={skip}
          >
            Skip
            <kbd class="kbd">S</kbd>
          </button>
          <button
            class="dock-btn dock-keep"
            class:dock-active-keep={currentDecision?.verdict === 'kept'}
            on:click={keep}
          >
            Keep
            <kbd class="kbd kbd-light">K · ↵</kbd>
          </button>
        </div>
      </div>

      <!-- Sidebar -->
      <div class="sidebar">
        <!-- Guidelines card -->
        <div class="card">
          <div class="sidebar-card-header">
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="header-icon"
              ><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path
                d="M14 3v5h5M8 13h8M8 17h6"
              /></svg
            >
            <span class="sidebar-card-title">Guidelines</span>
          </div>
          <div class="guidelines-list">
            {#if guidelinesLoading}
              <div class="guidelines-message">Loading guidelines...</div>
            {:else if guidelinesError}
              <div class="guidelines-message guidelines-error">
                {guidelinesError}
              </div>
            {:else if guidelines}
              <div class="guidelines-content">
                {@html guidelinesHtml}
              </div>
            {:else}
              <div class="guidelines-message">No guidelines provided.</div>
            {/if}
          </div>
        </div>

        <!-- Status card -->
        <div class="card">
          <div class="sidebar-card-header-plain">
            <span class="sidebar-card-title">Status</span>
          </div>
          <div class="status-grid">
            {#each [{ l: 'kept', n: counts.totalKept, color: 'var(--v2-kept)' }, { l: 'removed', n: counts.totalRemoved, color: 'var(--v2-removed)' }, { l: 'skipped', n: counts.totalSkipped, color: 'var(--v2-skipped)' }, { l: 'added', n: counts.totalAdded, color: 'var(--v2-added)' }] as x}
              <div class="status-cell">
                <div class="status-label">
                  <span class="status-dot" style:background={x.color}></span>
                  {x.l}
                </div>
                <div class="status-val" style:color={x.color}>{x.n}</div>
              </div>
            {/each}
          </div>
        </div>

        <!-- Source position -->
        <div class="position-note">
          Source {sourceIdx + 1} of {items.length} in this queue
        </div>
      </div>
    </div>
  {/if}

  <!-- ── REASON MODAL (Fix 5 — required for Keep / Remove) ──────────────── -->
  {#if reasonModal}
    <div class="modal-overlay" on:click={cancelReason} role="dialog" aria-modal="true">
      <div class="modal" on:click|stopPropagation>
        <div class="modal-header">
          <div>
            <div
              class="modal-title"
              style:color={reasonModal.pendingVerdict === 'keep' ? 'var(--v2-kept)' : 'var(--v2-removed)'}
            >
              {reasonVerbLabel}: {src?.title}
            </div>
            <div class="modal-subtitle">
              Provide a reason before confirming — it will appear in the decisions list and audit
              CSV.
            </div>
          </div>
          <button class="modal-close" on:click={cancelReason}>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg
            >
          </button>
        </div>
        <div class="modal-body">
          <div class="field-group">
            <label class="field-label" for="reason-input">
              Reason <span class="required-star">*</span>
            </label>
            <textarea
              id="reason-input"
              class="reason-textarea"
              bind:value={reasonText}
              placeholder="Why are you {reasonModal.pendingVerdict === 'keep'
                ? 'keeping'
                : 'removing'} this source?"
              rows="4"
              autofocus
            ></textarea>
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" on:click={cancelReason}>Cancel</button>
          <button
            class="btn btn-primary"
            class:btn-dim={!reasonCanConfirm}
            style:background={reasonModal.pendingVerdict === 'keep' ? 'var(--v2-kept)' : 'var(--v2-removed)'}
            on:click={confirmReason}
          >
            Confirm {reasonVerbLabel}
          </button>
        </div>
      </div>
    </div>
  {/if}

  <!-- ── PROPOSE NEW SOURCE MODAL ──────────────────────────────────────── -->
  {#if showPropose}
    <div
      class="modal-overlay"
      on:click={() => (showPropose = false)}
      role="dialog"
      aria-modal="true"
    >
      <div class="modal" on:click|stopPropagation>
        <div class="modal-header">
          <div>
            <div class="modal-title">Propose a new source</div>
            <div class="modal-subtitle">
              The source will be added to the project's Added list for review.
            </div>
          </div>
          <button class="modal-close" on:click={() => (showPropose = false)}>
            <svg
              width="14"
              height="14"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18" /></svg
            >
          </button>
        </div>
        <div class="modal-body">
          <div class="field-group">
            <label class="field-label">Source name</label>
            <input
              class="field-input"
              bind:value={proposeLabel}
              placeholder="e.g. Maryland Matters"
            />
          </div>
          <div class="field-group">
            <label class="field-label">Website URL</label>
            <input
              class="field-input"
              bind:value={proposeUrl}
              type="url"
              placeholder="e.g. marylandmatters.org"
            />
          </div>
        </div>
        <div class="modal-footer">
          <button class="btn" on:click={() => (showPropose = false)}>Cancel</button>
          <button
            class="btn btn-primary"
            class:btn-dim={!proposeLabel.trim() || !proposeUrl.trim()}
            on:click={submitPropose}>Add source</button
          >
        </div>
      </div>
    </div>
  {/if}

  <!-- ── TOAST ──────────────────────────────────────────────────────────── -->
  {#if proposeToast}
    <div class="toast">{proposeToast}</div>
  {/if}
</div>

<style>
  .review-page {
    width: 100%;
    min-height: 880px;
    background: var(--v2-bg);
    color: var(--v2-ink);
    font-family: var(--v2-sans);
    padding-bottom: 36px;
  }

  /* ── All-done state ── */
  .done-wrap {
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 70vh;
    padding: 40px;
  }
  .done-card {
    text-align: center;
    background: var(--v2-card);
    border: 1px solid var(--v2-line);
    border-radius: 20px;
    padding: 44px 52px;
    max-width: 480px;
  }
  .done-icon {
    width: 48px;
    height: 48px;
    border-radius: 50%;
    background: var(--v2-accent);
    color: #fff;
    display: grid;
    place-items: center;
    margin: 0 auto 20px;
  }
  .done-h2 {
    font-size: 28px;
    font-weight: 600;
    letter-spacing: -0.7px;
    margin: 0 0 8px;
  }
  .done-sub {
    font-size: var(--v2-text-body);
    color: var(--v2-body);
    margin: 0 0 28px;
    line-height: 1.5;
  }
  .done-tally {
    display: flex;
    gap: 16px;
    justify-content: center;
    flex-wrap: wrap;
    margin-bottom: 28px;
  }
  .done-stat {
    display: flex;
    align-items: center;
    gap: 6px;
    font-size: var(--v2-text-body);
  }
  .done-dot {
    width: 8px;
    height: 8px;
    border-radius: 2px;
    flex-shrink: 0;
  }
  .done-n {
    font-weight: 600;
    font-family: var(--v2-mono);
  }
  .done-l {
    color: var(--v2-body);
  }
  .done-actions {
    display: flex;
    gap: 10px;
    justify-content: center;
  }

  /* ── Action bar ── */
  .action-bar-wrap {
    padding: 34px 120px 0;
  }
  .action-bar {
    padding: 10px 14px;
    display: flex;
    align-items: center;
    gap: 10px;
    background: rgba(255, 255, 255, 0.84);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border: 1px solid var(--v2-line);
    border-radius: 16px;
  }
  .action-divider {
    height: 18px;
    width: 1px;
    background: var(--v2-line);
    flex-shrink: 0;
  }
  .action-spacer {
    flex: 1;
  }
  .progress-pill {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 5px 12px;
    background: var(--v2-surface);
    border: 1px solid var(--v2-line);
    border-radius: 8px;
    font-size: var(--v2-text-body);
  }
  .progress-current {
    font-weight: 600;
    font-family: var(--v2-mono);
  }
  .progress-sep {
    color: var(--v2-mute);
    font-family: var(--v2-mono);
  }
  .progress-mini-track {
    width: 52px;
    height: 4px;
    background: var(--v2-line);
    border-radius: 999px;
    overflow: hidden;
    flex-shrink: 0;
  }
  .progress-mini-fill {
    height: 100%;
    background: var(--v2-accent);
    border-radius: 999px;
    transition: width 0.2s;
  }
  .progress-pct-label {
    font-size: var(--v2-text-secondary);
    color: var(--v2-mute);
    font-family: var(--v2-mono);
    min-width: 28px;
  }

  /* ── Main grid ── */
  .main-grid {
    padding: 34px 120px 0;
    display: grid;
    grid-template-columns: 1fr 340px;
    gap: 28px;
    align-items: flex-start;
  }

  /* ── Cards ── */
  .card {
    background: var(--v2-card);
    border: 1px solid var(--v2-line);
    border-radius: 16px;
    overflow: hidden;
  }

  /* ── Buttons ── */
  .btn {
    box-shadow: 0 1px 0 rgba(0, 0, 0, 0.02);
  }
  .btn-primary {
    background: var(--v2-ink);
    color: #fff;
    border: none;
    box-shadow:
      0 1px 0 rgba(0, 0, 0, 0.04),
      inset 0 1px 0 rgba(255, 255, 255, 0.18);
  }
  .btn-accent {
    background: var(--v2-accent);
    color: #fff;
    border: none;
  }
  .btn-dim {
    opacity: 0.5;
    pointer-events: none;
  }

  /* ── Source header ── */
  .source-header {
    padding: 24px 28px 8px;
  }
  .source-header-row {
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 16px;
  }
  .source-header-left {
    flex: 1;
    min-width: 0;
  }
  .source-nav {
    display: flex;
    gap: 8px;
    flex-shrink: 0;
    padding-top: 4px;
  }
  .nav-circle {
    width: 46px;
    height: 46px;
    border-radius: 50%;
    border: 1px solid var(--v2-line);
    background: var(--v2-card);
    color: var(--v2-body);
    cursor: pointer;
    display: grid;
    place-items: center;
    transition:
      border-color 0.15s,
      color 0.15s,
      background 0.15s;
    flex-shrink: 0;
  }
  .nav-circle:hover:not(:disabled) {
    border-color: var(--v2-accent);
    color: var(--v2-accent);
    background: var(--v2-surface);
  }
  .nav-circle:disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }
  .chips-row {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-top: 10px;
    flex-wrap: wrap;
  }
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 3px 9px;
    border-radius: 999px;
    font-size: var(--v2-text-secondary);
    font-weight: 500;
  }
  .chip-decided {
    font-weight: 600;
  }
  .chip-dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  .source-title {
    font-size: 50px;
    font-weight: 600;
    letter-spacing: -1.2px;
    line-height: 1.02;
    margin: 0;
    color: var(--v2-ink);
  }
  .source-links {
    display: flex;
    align-items: center;
    gap: 22px;
    margin-top: 12px;
    font-size: var(--v2-text-secondary);
    flex-wrap: wrap;
  }
  .source-link-static {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--v2-body);
  }
  .source-link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--v2-accent);
    text-decoration: none;
    font-weight: 500;
  }
  .source-link:hover {
    text-decoration: underline;
  }
  .prev-reason {
    margin-top: 8px;
    font-size: var(--v2-text-secondary);
    color: var(--v2-mute);
    font-style: italic;
  }

  /* ── AI reviewer ── */
  .ai-box {
    margin: 14px 28px 0;
    padding: 12px 16px;
    border: 1px solid var(--v2-line);
    border-radius: 12px;
    background: var(--v2-surface);
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .ai-box-label {
    font-size: var(--v2-text-caption);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.6px;
    color: var(--v2-added);
  }
  .ai-box-by {
    font-weight: 500;
    color: var(--v2-mute);
  }
  .ai-box-text {
    font-size: var(--v2-text-control);
    color: var(--v2-body);
    line-height: 1.5;
    word-break: break-word;
  }
  .ai-box-evidence {
    font-size: var(--v2-text-caption);
    color: var(--v2-mute);
  }

  /* ── Metadata ── */
  .meta-heading-row {
    border-top: 1px solid var(--v2-line-soft);
    margin-top: 18px;
    padding: 14px 28px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .meta-heading {
    font-size: var(--v2-text-heading);
    font-weight: 600;
  }
  .meta-hint {
    font-size: var(--v2-text-secondary);
    color: var(--v2-mute);
  }
  .meta-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    border-top: 1px solid var(--v2-line-soft);
  }
  .meta-cell {
    padding: 18px 22px;
  }
  .meta-cell.has-right-border {
    border-right: 1px solid var(--v2-line-soft);
  }
  .meta-label {
    font-size: var(--v2-text-body);
    color: var(--v2-mute);
    letter-spacing: 0.5px;
    text-transform: uppercase;
    font-weight: 500;
  }
  .meta-value {
    font-size: var(--v2-text-body);
    font-weight: 600;
    letter-spacing: -0.4px;
    margin-top: 6px;
  }
  .meta-actions {
    margin-top: 14px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .meta-edit-input {
    width: 100%;
    margin-top: 6px;
    padding: 7px 10px;
    border: 1.5px solid var(--v2-accent);
    border-radius: 8px;
    font-size: var(--v2-text-control);
    font-weight: 500;
    font-family: var(--v2-sans);
    outline: none;
    background: #fff;
    color: var(--v2-ink);
  }
  .meta-edit-actions {
    display: flex;
    gap: 6px;
    margin-top: 10px;
  }
  .correct-label {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    font-size: var(--v2-text-control);
    color: var(--v2-body);
    cursor: pointer;
    background: none;
    border: none;
    padding: 0;
    font-family: var(--v2-sans);
  }
  .correct-label.correct-yes {
    color: var(--v2-accent-ink);
  }
  .checkbox {
    width: 15px;
    height: 15px;
    border-radius: 4px;
    background: #fff;
    border: 1.5px solid var(--v2-line);
    display: grid;
    place-items: center;
    flex-shrink: 0;
  }
  .checkbox.checked {
    background: var(--v2-accent);
    border-color: var(--v2-accent);
  }
  .meta-local-note {
    padding: 8px 28px 14px;
    font-size: var(--v2-text-secondary);
    color: var(--v2-mute);
    display: flex;
    align-items: flex-start;
    gap: 6px;
    border-top: 1px solid var(--v2-line-soft);
    line-height: 1.5;
  }
  .meta-local-note svg {
    flex-shrink: 0;
    margin-top: 1px;
  }

  /* ── Decision dock ── */
  .decision-dock {
    padding: 16px 22px;
    display: flex;
    align-items: center;
    gap: 10px;
  }
  .dock-label {
    font-size: var(--v2-text-secondary);
    color: var(--v2-mute);
    letter-spacing: 0.5px;
    text-transform: uppercase;
    font-weight: 500;
    margin-right: 6px;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .dock-btn {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 13px 14px;
    border-radius: 12px;
    font-family: var(--v2-sans);
    font-size: var(--v2-text-control);
    font-weight: 500;
    cursor: pointer;
    transition:
      opacity 0.12s,
      box-shadow 0.15s;
  }
  .dock-btn:hover {
    opacity: 0.85;
  }
  .dock-btn:active {
    opacity: 0.7;
    transform: scale(0.98);
  }
  .dock-remove {
    background: #fff;
    border: 1px solid var(--v2-removed-soft);
    color: var(--v2-removed);
  }
  .dock-skip {
    background: #fff;
    border: 1px solid var(--v2-skipped-soft);
    color: var(--v2-skipped);
  }
  .dock-keep {
    flex: 1.4;
    background: var(--v2-kept);
    border: none;
    color: #fff;
    font-weight: 600;
    box-shadow:
      0 2px 0 rgba(0, 0, 0, 0.06),
      inset 0 1px 0 rgba(255, 255, 255, 0.18);
  }
  /* Active highlights for re-decide (Fix 3) */
  .dock-active-keep {
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--v2-kept) 35%, transparent),
      inset 0 1px 0 rgba(255, 255, 255, 0.18) !important;
  }
  .dock-active-remove {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--v2-removed) 22%, transparent) !important;
    background: var(--v2-removed-soft) !important;
  }
  .dock-active-skip {
    box-shadow: 0 0 0 3px color-mix(in srgb, var(--v2-skipped) 35%, transparent) !important;
    background: var(--v2-skipped-soft) !important;
  }
  .kbd {
    padding: 1.5px 6px;
    background: rgba(0, 0, 0, 0.07);
    border-radius: 4px;
    font-size: var(--v2-text-caption);
    font-family: var(--v2-mono);
    font-weight: 500;
    color: inherit;
  }
  .kbd-light {
    background: rgba(255, 255, 255, 0.22);
    color: #fff;
  }

  /* ── Sidebar ── */
  .sidebar {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .sidebar-card-header {
    padding: 12px 18px;
    border-bottom: 1px solid var(--v2-line-soft);
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .sidebar-card-header-plain {
    padding: 12px 18px;
    border-bottom: 1px solid var(--v2-line-soft);
  }
  .sidebar-card-title {
    font-size: var(--v2-text-heading);
    font-weight: 600;
  }
  .header-icon {
    color: var(--v2-accent);
  }
  .guidelines-list {
    padding: 10px 18px 14px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .guidelines-content {
    overflow-wrap: anywhere;
    max-height: 320px;
    overflow-y: auto;
    font-size: var(--v2-text-body);
    line-height: 1.6;
    color: var(--v2-body);
  }

  .guidelines-content :global(h1),
  .guidelines-content :global(h2),
  .guidelines-content :global(h3),
  .guidelines-content :global(h4),
  .guidelines-content :global(h5),
  .guidelines-content :global(h6) {
    font-size: var(--v2-text-heading);
    line-height: 1.3;
    color: var(--v2-ink);
    margin: 1em 0 0.5em;
  }
  .guidelines-content :global(p),
  .guidelines-content :global(ul),
  .guidelines-content :global(ol),
  .guidelines-content :global(blockquote),
  .guidelines-content :global(pre) {
    margin: 0 0 0.75em;
  }
  .guidelines-content :global(ul),
  .guidelines-content :global(ol) {
    padding-left: 1.5em;
  }
  .guidelines-content :global(a) {
    color: var(--v2-accent-ink);
    text-decoration: underline;
  }
  .guidelines-content :global(blockquote) {
    border-left: 2px solid var(--v2-line);
    padding-left: 0.75em;
  }
  .guidelines-content :global(pre) {
    white-space: pre-wrap;
  }
  .guidelines-content :global(code) {
    font-family: var(--v2-mono);
  }
  .guidelines-content :global(> :first-child) {
    margin-top: 0;
  }

  .guidelines-message {
    font-size: var(--v2-text-body);
    line-height: 1.6;
    color: var(--v2-mute);
  }

  .guidelines-error {
    color: #b42318;
  }
  .status-grid {
    padding: 14px 18px;
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 10px;
  }
  .status-cell {
    padding: 10px 12px;
    background: var(--v2-surface);
    border-radius: 10px;
    border: 1px solid var(--v2-line-soft);
  }
  .status-label {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: var(--v2-text-secondary);
    color: var(--v2-mute);
    text-transform: uppercase;
    letter-spacing: 0.6px;
    font-weight: 500;
  }
  .status-dot {
    width: 7px;
    height: 7px;
    border-radius: 2px;
    flex-shrink: 0;
  }
  .status-val {
    font-size: var(--v2-text-body);
    font-weight: 600;
    letter-spacing: -0.5px;
    font-family: var(--v2-mono);
    margin-top: 4px;
    transition: color 0.2s;
  }
  .position-note {
    font-size: var(--v2-text-secondary);
    color: var(--v2-mute);
    text-align: center;
    font-family: var(--v2-mono);
    padding: 0 4px;
  }

  /* ── Reason modal (Fix 5) ── */
  .reason-textarea {
    width: 100%;
    box-sizing: border-box;
    padding: 12px 14px;
    border-radius: 10px;
    border: 1.5px solid var(--v2-line);
    font-size: var(--v2-text-control);
    font-family: var(--v2-sans);
    color: var(--v2-ink);
    outline: none;
    resize: vertical;
    line-height: 1.5;
    background: var(--v2-surface);
  }
  .reason-textarea:focus {
    border-color: var(--v2-accent);
  }
  .required-star {
    color: var(--v2-accent);
    font-weight: 700;
  }

  /* ── Modals (shared) ── */
  .modal-overlay {
    position: fixed;
    inset: 0;
    background: rgba(20, 23, 30, 0.38);
    backdrop-filter: blur(4px);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }
  .modal {
    background: var(--v2-card);
    border: 1px solid var(--v2-line);
    border-radius: 20px;
    width: 480px;
    max-width: 96vw;
    box-shadow: 0 24px 60px -20px rgba(0, 0, 0, 0.28);
    overflow: hidden;
  }
  .modal-header {
    padding: 20px 22px;
    border-bottom: 1px solid var(--v2-line-soft);
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    gap: 14px;
  }
  .modal-title {
    font-size: var(--v2-text-heading);
    font-weight: 600;
  }
  .modal-subtitle {
    font-size: var(--v2-text-secondary);
    color: var(--v2-mute);
    margin-top: 4px;
    line-height: 1.4;
  }
  .modal-close {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--v2-mute);
    padding: 4px;
    border-radius: 6px;
    flex-shrink: 0;
  }
  .modal-body {
    padding: 18px 22px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  .modal-footer {
    padding: 14px 22px;
    border-top: 1px solid var(--v2-line-soft);
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 10px;
  }
  .field-group {
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .field-label {
    font-size: var(--v2-text-secondary);
    font-weight: 500;
    color: var(--v2-body);
  }
  .field-input {
    padding: 10px 14px;
    border-radius: 10px;
    border: 1.5px solid var(--v2-line);
    font-size: var(--v2-text-control);
    font-family: var(--v2-sans);
    color: var(--v2-ink);
    outline: none;
    background: var(--v2-surface);
  }
  .field-input:focus {
    border-color: var(--v2-accent);
  }

  /* ── Toast ── */
  .toast {
    position: fixed;
    bottom: 24px;
    left: 50%;
    transform: translateX(-50%);
    padding: 10px 20px;
    border-radius: 999px;
    background: var(--v2-ink);
    color: #fff;
    font-size: var(--v2-text-body);
    font-weight: 500;
    font-family: var(--v2-sans);
    box-shadow: 0 8px 24px -8px rgba(0, 0, 0, 0.28);
    z-index: 200;
    animation: fadeIn 0.2s ease;
  }
  @keyframes fadeIn {
    from {
      opacity: 0;
      transform: translateX(-50%) translateY(8px);
    }
    to {
      opacity: 1;
      transform: translateX(-50%) translateY(0);
    }
  }
</style>
