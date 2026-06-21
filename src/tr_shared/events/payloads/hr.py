"""Typed payloads for hr.* events (tr-people-finance HR module).

Each HR event is built inline by a single ``HREventPublisher.emit_*`` method with
a fixed key set (no caller-supplied dicts), so every shape here is unambiguous.
Unlike the finance publisher, the HR publisher does NOT inject entity_type/entity_id
— the emit method writes them into ``data`` directly, so they are modelled as
ordinary fields.

Field sets mirror app/modules/hr/core/event_publisher.py:emit_*. All ids are str
(UUIDs stringified at emit).
"""

from tr_shared.events.payloads._base import EventPayload


class HREventV1(EventPayload):
    """Common fields present in every HR domain event data dict."""

    entity_id: str
    entity_type: str
    action: str
    notification_event: str


class HRManualEntryCreatedV1(HREventV1):
    """hr.attendance.manual_entry.created (a new manual attendance entry)."""

    manual_entry_id: str
    employee_id: str
    attendance_id: str | None = None


class HRAttendanceCorrectionV1(HREventV1):
    """A correction against an existing attendance record.

    Identical shape for the correction-created event and the correction
    decision (approved/rejected) events — they differ only in ``action``.
    """

    manual_entry_id: str
    attendance_id: str
    employee_id: str


class HRSyncFailedV1(HREventV1):
    """hr.sync.failed — generic HR sync failure (attendance or employee sync)."""

    sync_type: str
    error: str
    task_id: str | None = None


class HRJobPostingPublishedV1(HREventV1):
    """hr.job_posting.published."""

    job_id: str
    title: str
    slug: str
    share_url: str | None = None


class HRJobPostingClosedV1(HREventV1):
    """hr.job_posting.closed."""

    job_id: str
    title: str


class HRApplicationSubmittedV1(HREventV1):
    """hr.application.submitted — a candidate submitted an application.

    Public-applicant flow: there is no actor user, so ``notification_event`` and
    actor routing tolerate absence; the emit method passes actor_id=None.
    """

    application_id: str
    job_id: str


class HRApplicationStageChangedV1(HREventV1):
    """hr.application.stage_changed (also reused for hired/rejected terminal moves).

    Differs only by ``action`` / ``new_stage`` across the stage-changed, hired,
    and rejected events — mirrors the HRAttendanceCorrectionV1 reuse pattern.
    """

    application_id: str
    job_id: str
    new_stage: str
    old_stage: str | None = None
