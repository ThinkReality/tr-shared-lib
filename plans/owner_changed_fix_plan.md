# ⚠️ Permanent Fix Required: tr-shared-lib `ListingEvents.OWNER_CHANGED`

**Priority:** HIGH  
**Reported:** 2026-04-24  
**Discovered by:** April-22 sprint gap audit (Feature-2k)  
**Status:** Container patched (temporary). Upstream source fix required.

---

## Problem

The `tr-listing-service` codebase uses `ListingEvents.OWNER_CHANGED` in 
`app/services/listings/listing_audit_service.py`:

```python
# listing_audit_service.py — _resolve_events()
if action_type == "update" and {"listing_owner", "listing_agent"} & set(changed):
    events.append(ListingEvents.OWNER_CHANGED)
```

However, the **tr-shared-lib package** installed in the Docker container image 
does NOT define `OWNER_CHANGED` in its `ListingEvents` class.

**Runtime impact:** Any listing `update` that changes `listing_owner` or `listing_agent` 
fields will cause an `AttributeError` in `_resolve_events()`, which is silently caught 
by the broad `except Exception` guard — meaning the event is dropped without notification.

---

## Temporary Fix (Applied)

Script: `docs/april-24/patch_tr_shared.py`

Adds `OWNER_CHANGED = "listing.owner_changed"` to the `ListingEvents` class in the 
container's installed venv. **This patch is lost on every `docker build` / image rebuild.**

```bash
# Re-apply after each rebuild:
docker exec backend-tr-listing-service-1 python /app/docs/april-24/patch_tr_shared.py
```

---

## Permanent Fix Required

In the `tr-shared-lib` source repository, edit:

**File:** `tr_shared/events/event_types.py`

```python
class ListingEvents:
    """Events produced by tr-listing-service."""

    CREATED = "listing.created"
    UPDATED = "listing.updated"
    PUBLISHED = "listing.published"
    UNPUBLISHED = "listing.unpublished"
    ARCHIVED = "listing.archived"
    VERIFIED = "listing.verified"
    REJECTED = "listing.rejected"
    RESUBMITTED = "listing.resubmitted"
    DOCUMENT_SUBMITTED = "listing.document_submitted"
    PUBLISH_REQUESTED = "listing.publish_requested"
    PRICE_CHANGED = "listing.price_changed"
    OWNER_CHANGED = "listing.owner_changed"   # ← ADD THIS LINE
```

Then release a new patch version of `tr-shared-lib` and update the `pyproject.toml` 
dependency pin in `tr-listing-service`.
