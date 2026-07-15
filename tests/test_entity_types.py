from tr_shared.contracts.entity_types import EntityType
from tr_shared.contracts.taxonomy import Feature

EXPECTED = {
    "lead", "deal", "contact", "property", "listing",
    "cms.blog", "cms.page",
    "lms.course", "lms.certificate",
    "task",
    "activity.comment",
    "hr.employee", "hr.application", "hr.offer",
    "hr.attendance_record", "hr.attendance_exception",
    "hr.attendance_manual_entry", "hr.attendance_sync_job",
    "finance.commission", "finance.invoice", "finance.expense",
    "admin.user",
    "media",
}


def test_entity_type_has_the_locked_members():
    assert {e.value for e in EntityType} == EXPECTED


def test_feature_prefix_resolves_for_dotted_values():
    assert EntityType.ACTIVITY_COMMENT.feature() is Feature.ACTIVITY
    assert EntityType.CMS_BLOG.feature() is Feature.CMS
    assert EntityType.ADMIN_USER.feature() is Feature.ADMIN
    assert EntityType.HR_ATTENDANCE_SYNC_JOB.feature() is Feature.HR


def test_feature_resolves_for_bare_values():
    assert EntityType.LEAD.feature() is Feature.LEAD
    assert EntityType.TASK.feature() is Feature.TASK
    assert EntityType.MEDIA.feature() is Feature.MEDIA


def test_every_entity_type_maps_to_a_real_feature():
    for entity in EntityType:
        assert isinstance(entity.feature(), Feature)
