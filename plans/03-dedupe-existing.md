# Plan 03 - Deduplicate Existing Duplicates (Safe Cleanup)

## Goal

Remove duplicates already created on the Trello board without deleting manually edited cards.

## Approach

Use the CLI `--dedupe` mode to:

- Scan open board cards.
- Group "same item" by `SyncKey=` when present, otherwise by `Canvas link:` URL.
- Keep the safest card in each group and archive only auto-managed duplicates.

## Heuristics (Keep Order)

1. Prefer a card that appears manually edited or moved (to avoid deleting user changes).
2. Prefer the card already tracked in state (if present).
3. Prefer a card still in its original list.
4. Otherwise, keep the most recently active card.

## Steps

1. Run: `python -m canvas_trello_sync --dedupe-dry-run`
2. Review output for groups that will be archived.
3. Run: `python -m canvas_trello_sync --dedupe`
4. Run a normal sync once to refresh state.

## Success Criteria

- Duplicate groups are reduced to a single card or left untouched if all candidates are manual edits.
- Manually modified cards are not archived.
