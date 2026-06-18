"""Typed payloads for cms.* events (tr-content-platform CMS module).

Canonical redesign of the landing-page / blog lifecycle events. The legacy emit
path built dynamic ``{action}_by`` keys (created_by/updated_by/published_by/…) and
recipient-fallback chains; here the actor is always ``actor_id`` and the
notification target is always the explicit ``recipient_id``. extra="forbid" means
a stray legacy key (e.g. ``created_by``) fails validation rather than passing
silently.

Field sets mirror app/modules/cms/services/landing_page/service.py and the blog
service emit sites. All ids are str (UUIDs stringified at emit).
"""

from enum import StrEnum
from typing import Any

from pydantic import Field

from tr_shared.contracts.entity_types import EntityType
from tr_shared.events.payloads._base import EventPayload


class CMSLifecycleAction(StrEnum):
    """Canonical lifecycle action values carried by CMS events."""

    CREATED = "created"
    UPDATED = "updated"
    DELETED = "deleted"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"
    REVIEW_REQUESTED = "review_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ARCHIVED = "archived"


class CMSPageEventV1(EventPayload):
    """Common shape for cms.page.* lifecycle events (created/deleted/unpublished).

    Subclasses add per-event fields; the plain lifecycle events use this directly.
    ``entity_type``/``entity_id`` are carried on the wire (the publish task injects
    them) and read by the notification/activity consumers for entity linking.
    """

    entity_type: EntityType
    entity_id: str
    page_id: str
    page_title: str
    page_slug: str
    action: CMSLifecycleAction
    actor_id: str | None = None
    actor_name: str | None = None
    recipient_id: str | None = None
    status: str | None = None


class CMSPageUpdatedV1(CMSPageEventV1):
    """cms.page.updated — carries the changed-field map."""

    changes: dict[str, Any] | None = None


class CMSPagePublishedV1(CMSPageEventV1):
    """cms.page.published — carries the public URL of the published page."""

    page_url: str | None = None


class CMSPageReviewRequestedV1(CMSPageEventV1):
    """cms.page.review_requested — who requested the review."""

    requested_by: str | None = None


class CMSPageApprovedV1(CMSPageEventV1):
    """cms.page.approved — reviewer notes + the now-public URL."""

    page_url: str | None = None
    review_notes: str | None = None


class CMSPageRejectedV1(CMSPageEventV1):
    """cms.page.rejected — reviewer notes (required by the workflow)."""

    review_notes: str | None = None


class CMSBlogEventV1(EventPayload):
    """Common shape for cms.blog.* lifecycle events.

    Mirrors CMSPageEventV1 but keyed on the blog identity (a blog and a page are
    distinct record kinds, so the id/title/slug fields are not shared).
    """

    entity_type: EntityType
    entity_id: str
    blog_id: str
    blog_title: str
    blog_slug: str | None = None  # blog events don't all carry a slug (e.g. bulk ops)
    action: CMSLifecycleAction
    actor_id: str | None = None
    actor_name: str | None = None
    recipient_id: str | None = None
    status: str | None = None


class CMSBlogUpdatedV1(CMSBlogEventV1):
    """cms.blog.updated — carries the changed-field map."""

    changes: dict[str, Any] | None = None


class CMSLandingPageMediaV1(EventPayload):
    """One media item attached to a published landing page."""

    media_id: str
    media_url: str
    category: str | None = None


class CMSLandingPageContextV1(EventPayload):
    """Nested project context carried by cms.landing_page.published.

    Consumed by the crm-core learning landing_page_consumer to build the page.
    """

    developer_name: str
    about_project_summary: str | None = None
    project_type: str
    project_status: str | None = None
    property_types: list[str] = Field(default_factory=list)
    starting_price: float | None = None
    starting_price_currency: str | None = None
    handover_date: str | None = None
    area_name: str | None = None
    community_name: str | None = None
    amenities: list[str] = Field(default_factory=list)
    media: list[CMSLandingPageMediaV1] = Field(default_factory=list)


class CMSLandingPagePublishedV1(EventPayload):
    """cms.landing_page.published — emitted to the LMS/learning pipeline."""

    project_id: str | None = None
    project_title: str
    landing_page_context: CMSLandingPageContextV1
