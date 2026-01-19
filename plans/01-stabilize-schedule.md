# Plan 01 - Stabilize Scheduled Runs (Stop Duplication)

## Goal

Make scheduled GitHub Actions runs idempotent so they do not recreate cards or drift state.

## Preconditions

- GitHub Actions enabled.
- Repo secrets set: `CANVAS_BASE_URL`, `CANVAS_TOKEN`, `TRELLO_KEY`, `TRELLO_TOKEN`, and one of `TRELLO_BOARD_ID`/`TRELLO_BOARD_URL`.
- Workflow present: `.github/workflows/canvas_trello_sync.yml`.

## Steps

1. **Stop manual "delete all cards"**
   - Do not delete cards before scheduled runs. That forces a rebuild every time.

2. **Run the scheduled workflow manually once (default branch)**
   - Actions -> "Canvas + Trello Sync" -> "Run workflow".

3. **Verify state restore and board match**
   - In workflow logs, confirm:
     - "State restored from run: <id>"
     - `state keys: ...` and non-zero `items`/`courses`
     - `board_id=...` in the sync start line

4. **Verify idempotency**
   - Run it again manually.
   - Confirm in logs that `cards_created` is ~0 (only new Canvas items should create cards).

5. **Enable schedule**
   - Re-enable the scheduled workflow once manual runs look stable.

## Success Criteria

- A second run without changes produces `cards_created=0` (or near-zero).
- No duplicate cards appear on the Trello board.
