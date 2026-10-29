# Importing AI reviews from the collection AI reviewer

The collection AI reviewer (`mediacloud-ai-reviewer`) checks a Media Cloud collection source by source and
records, for each source, what it decided and why. This tool can start a review project from that AI review, so
reviewers only need to decide what the AI could not settle, and send the decisions back so the AI reviewer can
rebuild the collection's final package. Existing projects and workflows are unchanged.

## How a project from the AI reviewer behaves

- **Way in:** `POST /api/review-projects/import-ai` with `{"url": ...}` or `{"proposal": {...}}`
  (schema `mediacloud-ai-review/1`), then generate reviewer queues as for any project.
- The AI's clear calls arrive prefilled: Keep, Remove (the AI's note or reason as the removal reason), Skip (its
  reason as the skip note), Add for confirmed additions. An "add" on a source already in the collection becomes
  Keep. Prefilled decisions have **no `decided_at`**.
- Every reviewer decision, including Skip, sets `decided_at`. A decision with `decided_at` was made by a person; one
  without it is the AI's prefill (or still undecided).
- Items the AI left undecided are spread evenly over the reviewer queues.
- Additions already in Media Cloud's directory keep their source id, so Publish attaches that source instead of
  creating a duplicate. Collections Media Cloud does not have yet (no collection id) can be imported too.
- The AI's guidelines become the project's guidelines.
- Each item carries the AI's call as `item.ai` (`decision`, `proposal`, `decided_by`, `reason`, `note`,
  `why_human`, `evidence`). The audit CSV of an imported project gains `ai_decision`, `ai_decided_by`,
  `ai_reason` and `decided_at`.
- **Way back:** `GET /api/review-projects/<guid>/ai-decisions` returns the decisions in the AI reviewer's format
  (schema `mediacloud-ai-review-decisions/1`); `POST /api/review-projects/<guid>/ai-decisions/send` posts them to the
  callback address given in the AI review.

## In the demo UI (`/demo/*`)

- **Projects page (`/demo/manage`):** **Import AI review** opens a form taking an AI reviewer link or a downloaded
  JSON file, an optional project name and the number of reviewer queues; it imports the review, creates the
  queues and opens the project. `/demo/manage?import=<url>` opens the form with the link filled in.
- **Review screen:** each source from an AI review shows an **AI reviewer** box with the AI's call, why it was left
  to the reviewer, its reason and Media Cloud's counts. While the shown decision is still the AI's prefill, the box
  says so.
- **Project page:** an **AI review** card links to where the review came from, offers **Send decisions to the AI
  reviewer** (when the review has a trusted callback) and **Decisions as JSON**.

## Configuration and security

| Variable | Purpose |
|---|---|
| `AI_REVIEWER_BASE_URL` | The trusted AI reviewer, e.g. `https://ai-reviewer.example.org/api`. |
| `AI_REVIEWER_TOKEN` | Bearer token for the AI reviewer's API (its `APP_TOKEN`), if it has one. |

The backend makes requests only to the configured AI reviewer:

- An AI review is fetched by URL only when the URL is under `AI_REVIEWER_BASE_URL` (same scheme, host and port,
  within its path). URLs with credentials, `..` segments, backslashes or whitespace are refused. Redirects are not
  followed. Without `AI_REVIEWER_BASE_URL`, import by URL is disabled; an AI review can still be imported as JSON.
- The callback address inside an AI review is kept only when it is under `AI_REVIEWER_BASE_URL` (otherwise the
  import returns a warning), and is checked again before decisions are sent.
- `AI_REVIEWER_TOKEN` is attached only to requests to addresses under `AI_REVIEWER_BASE_URL`.

The AI reviewer must be reachable from this tool, both to fetch AI reviews and to receive decisions.

## Data

Migration 13 in `backend/run_migrations.py` adds nullable text columns (SQLite and Postgres; safe to run again):
`review_projects.ai_source_url`, `ai_callback_url`, `ai_proposal_json`; `review_project_sources.ai_json`;
`review_items.ai_json`.
