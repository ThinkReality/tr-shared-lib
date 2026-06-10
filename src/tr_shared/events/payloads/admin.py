"""Typed payloads for admin.* events (tr-crm-core admin module).

Field sets mirror the dicts emitted by app/modules/admin/services/*.
``IntegrationPlatformEventV1`` moved here from crm-core (now EventPayload-based,
str ids — callers stringify UUIDs at emit). All ids are str.
"""

from pydantic import Field

from tr_shared.events.payloads._base import EventPayload


class AdminLeadSourceCreatedV1(EventPayload):
    lead_source_id: str
    source_name: str


class AdminLeadSourceUpdatedV1(EventPayload):
    lead_source_id: str
    source_name: str


class AdminLeadSourceDeletedV1(EventPayload):
    lead_source_id: str


class AdminAssignmentRuleCreatedV1(EventPayload):
    rule_id: str
    rule_name: str


class AdminLeadScoringCreatedV1(EventPayload):
    config_id: str


class AdminLeadScoringUpdatedV1(EventPayload):
    config_id: str


class AdminLeadScoringDeletedV1(EventPayload):
    config_id: str | None = None
    # delete-one emits an int (1); delete-all emits the string "all".
    deleted_count: int | str


class AdminNurtureCampaignCreatedV1(EventPayload):
    campaign_id: str
    campaign_name: str


class AdminNurtureCampaignUpdatedV1(EventPayload):
    campaign_id: str
    campaign_name: str


class AdminModuleConfigurationUpdatedV1(EventPayload):
    module_count: int


class IntegrationPlatformEventV1(EventPayload):
    schema_version: str = Field(default="1.0", pattern=r"^1\.\d+$")
    platform_id: str
    platform_name: str
    tenant_id: str
    webhook_token: str | None = None
