# HR Attendance Event Contract Changes - 2026-05-23

Author: ThinkRealty backend team

Branch: `feat/hr-attendance-integration-may23`

Target: `main`

Scope: Shared HR attendance event vocabulary.

## Change

`src/tr_shared/events/event_types.py` now exports standard HR attendance workflow event constants:

```python
ATTENDANCE_SYNC_FAILED = "hr.attendance.sync_failed"
ATTENDANCE_EXCEPTION_CREATED = "hr.attendance.exception.created"
ATTENDANCE_EXCEPTION_RESOLVED = "hr.attendance.exception.resolved"
ATTENDANCE_MANUAL_ENTRY_CREATED = "hr.attendance.manual_entry.created"
ATTENDANCE_MANUAL_ENTRY_APPROVED = "hr.attendance.manual_entry.approved"
ATTENDANCE_MANUAL_ENTRY_REJECTED = "hr.attendance.manual_entry.rejected"
ATTENDANCE_RECORD_CORRECTED = "hr.attendance.record.corrected"
```

## Reason

HR producers, activity consumers, and notification consumers need a shared event contract rather than duplicated event-name literals.

## Verification

- The changed event type module passes Ruff when evaluated with the workspace Ruff environment.
- Full library tests currently report `10` existing failures in async-runner and PropertyFinder integration tests unrelated to these new constants.
