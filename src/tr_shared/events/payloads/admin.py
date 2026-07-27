"""Typed payloads for admin.* events (tr-crm-core admin module).

Field sets mirror the dicts emitted by app/modules/admin/services/*.
All ids are str — callers stringify UUIDs at emit.
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


class AdminAssignmentRuleUpdatedV1(EventPayload):
    rule_id: str
    rule_name: str


class AdminAssignmentRuleDeletedV1(EventPayload):
    rule_id: str


class AdminAgentGroupCreatedV1(EventPayload):
    group_id: str
    group_name: str


class AdminAgentGroupUpdatedV1(EventPayload):
    group_id: str
    group_name: str


class AdminAgentGroupDeletedV1(EventPayload):
    group_id: str


class AdminModuleConfigurationUpdatedV1(EventPayload):
    module_count: int


class AdminTenantSiteCreatedV1(EventPayload):
    site_id: str
    key_hash: str = Field(
        ...,
        description="SHA-256 hex of the site key — cache invalidation key, never the key itself",
    )


class AdminTenantSiteUpdatedV1(EventPayload):
    site_id: str
    key_hash: str
    previous_key_hash: str | None = Field(
        None,
        description=(
            "Set on rotation. The gateway must evict THIS hash — the old key is "
            "still cached and would otherwise keep working until its 30-min TTL."
        ),
    )


class AdminTenantSiteDeletedV1(EventPayload):
    site_id: str
    key_hash: str


class IntegrationPlatformEventV1(EventPayload):
    schema_version: str = Field(default="1.0", pattern=r"^1\.\d+$")
    platform_id: str
    platform_name: str
    tenant_id: str
    webhook_token: str | None = None
