# User Panel Release Notes

## Version Scope
- Project: PCAN_Viewer_JJ_R007
- Area: User Panel (v2 modular architecture)
- Date: 2026-07-30

## What Was Added
- Mode state machine: EDIT / STANDBY / RUN.
- Edit mode password gate integration from main configuration.
- TX/RX tool split creation flow.
- Group/Tab parent-child composition.
- Shape tools and draw mode (rect/line).
- Drag move + bottom-right drag resize.
- Numeric geometry editor (row/col/row_span/col_span).
- Z-order controls (front/back/forward/backward).
- TX overlap diagnostics with list highlighting and conflict focus navigation.
- Per-frame TX staging/flush policy and cycle mode support.
- Package persistence: .pjjupkg with panel JSON + DB bundle.
- CAN-free RX simulator (manual apply + auto simulation).

## Behavior Changes
- TX emission path now stages values by frame and flushes with policy-aware timers.
- Widgets using same frame can operate together without immediate overwrite.
- Edit operations are restricted by mode and optional password policy.

## Compatibility
- Existing import path compatibility preserved through wrapper module.
- Existing main window DB handling remains compatible with package load replacement flow.

## Operational Notes
- Use STANDBY for validation without TX output.
- Use RUN for full TX/RX runtime.
- Run overlap check after adding/editing any TX mapping.

## Known Limitations
- Fallback bit-packing path currently supports little-endian only.
- Big-endian fallback encoding is not yet implemented.
- Final acceptance with real CAN hardware is still required.

## Recommended Validation Path
1. Execute USER_PANEL_ACCEPTANCE_CHECKLIST.md.
2. Record results in USER_PANEL_TEST_REPORT_TEMPLATE.md.
3. Confirm no critical FAIL/BLOCKED before release.
