"""Typed payloads for the admin.user.* / admin.role.* events the auth module
produces (tr-crm-core auth module — events are admin.*-namespaced, source=admin).

Field sets mirror the dicts emitted by
app/modules/auth/services/users/{create_mixin,update_mixin}.py and
app/modules/auth/api/v1/endpoints/admin/role_routes.py. All ids are str.
"""

from tr_shared.events.payloads._base import EventPayload


class AdminUserCreatedV1(EventPayload):
    user_id: str
    user_name: str
    email: str
    role_names: list[str]
    recipient_id: str


class AdminUserUpdatedV1(EventPayload):
    user_id: str
    user_name: str
    email: str
    changed_fields: list[str]
    recipient_id: str


class AdminRoleAssignedV1(EventPayload):
    user_id: str
    user_name: str
    role_id: str
    role_name: str
    assigned_by: str
    recipient_id: str
