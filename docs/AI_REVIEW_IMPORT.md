# Importing AI reviews from the collection AI reviewer

This branch (`feat/ai-review-import`) connects the tool to the collection AI reviewer (`mediacloud-ai-reviewer`),
which checks a collection source by source and hands what it cannot settle to people here. Existing projects and
the existing workflow are unchanged: the changes only add a way in (import an AI review) and a way back (send the
decisions).

## What the change adds

| Where | What |
|---|---|
| `backend/services/ai_reviewer.py` (new) | fetch and validate an AI review; create the project and its seed sources; fill each queue item with the AI's decision; collect the decisions in the AI reviewer's format and send them back |
| `backend/models.py` | `ReviewProject.ai_source_url`, `ai_callback_url`, `ai_proposal_json`; `ReviewProjectSource.ai_json`; `ReviewItem.ai_json`, returned as `item.ai` |
| `backend/run_migrations.py` | migration 13: the five new text columns (SQLite and Postgres; safe to run again) |
| `backend/routes/api.py` | `POST /api/review-projects/import-ai`; `GET /api/review-projects/<guid>/ai-decisions`; `POST /api/review-projects/<guid>/ai-decisions/send`. Queue generation fills items from the AI, spreads the items left for people evenly over the queues, adds the AI's new sources, and accepts proposed collections (no Media Cloud id). New sources from the AI export with their metadata and directory id. The audit export gains `ai_decision`, `ai_decided_by`, `ai_reason`, `decided_at`. |
| `backend/config.py` | `AI_REVIEWER_TOKEN`: the AI reviewer's API token |
| `frontend/src/routes/Home.svelte` | "Import an AI review" on the manage page (opens by itself on `/manage?import=<url>`) |
| `frontend/src/components/SourceViewer.svelte` | the blue "AI reviewer" box on each source: the AI's call, why it is left to the reviewer, Media Cloud's counts |
| `frontend/src/routes/ReviewProject.svelte` | the "AI review" panel: where the review came from, **Send decisions to the AI reviewer**, decisions as JSON |
| `frontend/src/lib/api.js` | `importAiReview`, `sendAiDecisions`, `getAiDecisionsUrl` |

## How a project from the AI reviewer behaves

- The AI's clear calls arrive filled in: Keep, Remove (its reason and an `[AI remove, rule:…]` tag as the removal
  reason), Add for confirmed additions, Skip for rows held for Media Cloud. They have no `decided_at`, so a
  person's later decision on them is recognisable.
- Reviewers' queues hold the items the AI left undecided, spread evenly. The project's guidelines are the AI
  reviewer's guidelines plus the list of those items and why each one is there.
- Additions already in Media Cloud's directory carry their source id. The existing Publish attaches that source
  instead of creating a new one (it creates sources only for items without an id).
- Everything else (virtual queues, exports, publish, metadata editing) works as for any project.

## Configuration and deployment

1. Deploy the branch as usual; `postdeploy.sh` / `run_migrations.py` adds the columns.
2. Set `AI_REVIEWER_TOKEN` to the AI reviewer's `APP_TOKEN`, if it has one.
3. The review tool must reach the AI reviewer (to fetch the review), and the AI reviewer's `PUBLIC_URL` must be
   reachable from the review tool (decisions go back to it).

## Tested

Locally, end to end, with El Salvador National (86 sources):
- import from the AI reviewer's link, two queues of 43 with 19 undecided items each, guidelines and AI box shown;
- decisions made in the queue (and through the API), sent back with the button;
- the AI reviewer wrote them into the pipeline, measured 33% agreement on the three AI calls the reviewer
  changed or checked, rebuilt and re-packaged the collection;
- migration 13 on a database created by the unchanged tool, run twice.

`run_migrations.py` prints ✓/✗, which a Windows console (cp1252) cannot encode. That is an existing upstream
issue, not part of this change: on Windows set `PYTHONIOENCODING=utf-8`.
