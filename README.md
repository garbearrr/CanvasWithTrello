# Canvas → Trello Sync

Sync upcoming Canvas assignments + course calendar events into Trello.

## Setup

1. Create a virtualenv and install deps:
   - `python -m venv .venv`
   - `.venv\\Scripts\\pip install -r requirements.txt`
2. Create `.env` from `.env.example` and fill in values.
   - Trello key/token can be generated from Trello's app key page (key + token must match).

## Run

- Run once: `python -m canvas_trello_sync --once`
- Poll every 30 minutes (default): `python -m canvas_trello_sync`
- Validate Trello auth + board access: `python -m canvas_trello_sync --validate`
- List active courses (helps find `CANVAS_TERM_ID`): `python -m canvas_trello_sync --list-courses`
- Wipe managed content then sync (archives only cards created by this tool; archives tool-created lists only if empty after wipe): `python -m canvas_trello_sync --once --wipe-board --wipe-board-confirm <BOARD_ID>`
- Debug logging: `python -m canvas_trello_sync --once --log-level DEBUG --log-http --log-texts`

Avoid `--log-level DEBUG` when using Trello auth (key/token are query params and can appear in HTTP debug logs).

By default, the sync scopes to the “current” term by selecting the largest `enrollment_term_id` returned by Canvas for active courses. Set `CANVAS_TERM_ID` to override.

Features:
- Creates a per-class Trello list and a top “Class Info” card (teacher info when available via Canvas API).
- Sorts the list by due date (earliest at top), keeping the info card pinned first.
- Creates a “Canvas Token” list with a countdown card using `CANVAS_TOKEN_CREATED_AT` + `CANVAS_TOKEN_LIFETIME_DAYS`.
- Creates a per-class Trello label (e.g. `CS 101`) with a distinct color (persisted in state) and applies it to all synced cards.
- Creates board-level `TODO` and `Done` lists at the bottom for manual organization.

## GitHub Actions (Scheduled)

This repo includes a scheduled workflow at `.github/workflows/canvas_trello_sync.yml` that runs every ~30 minutes.

1. Add repo secrets:
   - `CANVAS_BASE_URL`, `CANVAS_TOKEN`
   - `TRELLO_KEY`, `TRELLO_TOKEN`
   - One of: `TRELLO_BOARD_ID` or `TRELLO_BOARD_URL`
2. Optional secrets:
   - `DUE_WITHIN_DAYS`, `CANVAS_TOKEN_CREATED_AT`, `CANVAS_TOKEN_LIFETIME_DAYS`
3. Enable Actions + wait for the scheduled run, or run it manually via “Run workflow”.

The workflow persists `data/canvas_trello_state.json` using the Actions cache and uploads logs as an artifact.

State is stored in `data/canvas_trello_state.json` by default (configurable via `SYNC_STATE_FILE`).
