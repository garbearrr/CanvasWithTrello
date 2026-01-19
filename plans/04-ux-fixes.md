# Plan 04 - UX Fixes and Quality Improvements

## Goal

Close remaining polish issues (visual + text).

## A) Class Info Card Cover Rendering

1. Confirm Trello cover endpoint behavior:
   - Verify response payload and card `cover` fields after setting cover.
2. If needed, adjust request format:
   - Some Trello endpoints require query params vs body.
3. Validate in UI:
   - Confirm cover color appears.
   - Confirm cover size is `full` (full background).

## B) Canvas Description Missing Letters

1. Capture raw source:
   - Log raw `description` HTML from Canvas for an affected assignment.
2. Compare cleaning stages:
   - Before/after `html.unescape`, normalization, and control-char handling.
3. Refine sanitizer:
   - Fix regex escapes and whitespace normalization as needed.

## Success Criteria

- Info card cover consistently shows with correct color and full size.
- Descriptions no longer drop letters in common cases.
