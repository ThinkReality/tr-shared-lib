"""Single source of truth for cross-service (S2S) HTTP contracts.

Each module here owns one provider's internal contract: the route PATHS (as
builder functions, so a caller can never hardcode a path that drifts from the
provider → kills the silent-404 class) and the request/response MODELS the two
sides agree on (so a renamed field is a type error, not a silent ``None``).

Mechanism (chosen 2026-06-21): path builders + shared models in tr-shared.
- Providers mount their routes using these path constants and set
  ``response_model=`` to the shared model.
- Callers build URLs via the builder funcs and parse responses into the model.
- For rich provider models (e.g. listing-by-reference) the shared model is a
  LEAN "ref" of the fields callers actually read (``extra='ignore'``); a
  provider-side drift test guarantees the full model is a superset.

Scope: the ~12 live cross-service contracts only (not admin-tooling internal
endpoints with no S2S caller).
"""

from tr_shared.contracts.s2s.access_check import (
    AccessCheckRequest,
    AccessCheckResponse,
)

__all__ = [
    "AccessCheckRequest",
    "AccessCheckResponse",
]
