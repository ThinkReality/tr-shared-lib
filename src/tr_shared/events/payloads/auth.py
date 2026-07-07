"""Typed payloads for admin.user.* / admin.role.* events (tr-crm-core auth module).
Field sets mirror app/modules/auth/services/users/{create_mixin,update_mixin}.py — all ids are str."""

from tr_shared.events.payloads._base import EventPayload


class AdminUserCreatedV1(EventPayload):
    user_id: str
    user_name: str
    role_names: list[str]
    recipient_id: str


class AdminUserUpdatedV1(EventPayload):
    user_id: str
    user_name: str
    changed_fields: list[str]
    recipient_id: str


class AdminRoleAssignedV1(EventPayload):
    user_id: str
    user_name: str
    role_id: str
    role_name: str
    assigned_by: str
    recipient_id: str


class PortalAgentIdentityV1(EventPayload):
    portal: str
    external_id: str


class AdminPortalAgentPromotedV1(EventPayload):
    """Fired when a new user links previously-unmatched portal agents to a CRM user.
    Portal-data services (e.g. listings) re-point those agent records to crm_user_id."""

    crm_user_id: str
    agents: list[PortalAgentIdentityV1]
