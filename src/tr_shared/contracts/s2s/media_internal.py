"""S2S contract: tr-media-service media URL endpoint.

Provider: tr-media-service (/api/v1/media).
Caller: tr-crm-core (auth media_client).
"""

from uuid import UUID

BASE_PATH = "/api/v1/media"


def signed_url(media_file_id: UUID | str) -> str:
    return f"{BASE_PATH}/{media_file_id}/url"
