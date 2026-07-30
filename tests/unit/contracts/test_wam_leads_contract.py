"""The WAM lead paths are S2S-only and must sit under the /internal prefix.

WAM mounts GatewayHMACMiddleware, which rejects any unsigned request whose path
is not skip-listed. /api/v1/internal/ is the skip-listed prefix, so a lead path
outside it is unreachable for the service callers that use it.
"""

from uuid import uuid4

from tr_shared.contracts.s2s import wam_leads

_LEAD_ID = uuid4()


def test_base_path_is_internal():
    assert wam_leads.BASE_PATH == "/api/v1/internal/leads"


def test_every_builder_is_under_the_internal_prefix():
    built = (
        wam_leads.link(),
        wam_leads.start_conversation(),
        wam_leads.close_by_phone(),
        wam_leads.status(_LEAD_ID),
    )
    for path in built:
        assert path.startswith("/api/v1/internal/"), path


def test_builders_return_the_expected_paths():
    assert wam_leads.link() == "/api/v1/internal/leads/link"
    assert wam_leads.start_conversation() == "/api/v1/internal/leads/start-conversation"
    assert wam_leads.close_by_phone() == "/api/v1/internal/leads/close-by-phone"
    assert wam_leads.status(_LEAD_ID) == f"/api/v1/internal/leads/{_LEAD_ID}/status"
