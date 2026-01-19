# Plan 02 - One-Time Wipe (Managed) + Rebuild

## Goal

Do a one-time cleanup that mimics local `--wipe-board` behavior, then repopulate.

## Preconditions

- The wipe workflow exists: `.github/workflows/canvas_trello_wipe.yml`.
- You know the resolved Trello `board_id` (not the URL).

## Steps

1. **Get the board id**
   - Run: Actions -> "Canvas + Trello Sync" -> "Run workflow".
   - Read the `board_id=...` from the `--validate` output (or from logs).

2. **Run the wipe workflow**
   - Actions -> "Canvas + Trello Wipe (Managed)" -> "Run workflow".
   - Input `board_id` (required safety confirmation).
   - Set `full_wipe=true` only if you want to archive ALL open cards + lists.

3. **Confirm results**
   - Check the uploaded artifacts:
     - `canvas-trello-sync-state` was uploaded
     - `canvas-trello-sync-logs` contains wipe + sync logs

4. **Resume schedule**
   - Re-enable `.github/workflows/canvas_trello_sync.yml` schedule.

## Notes

- Managed wipe only archives tool-managed content and respects manual moves/edits.
- If state is missing or mismatched, re-run the normal sync to republish state or use `full_wipe`.
