import tr_shared.rate_limiter as rate_limiter


def test_no_pre_authentication_ip_limiter_is_offered():
    """Behind the gateway every caller shares one edge IP, so an app-wide IP limiter is one bucket for all."""
    assert not hasattr(rate_limiter, "RateLimitMiddleware")
    assert not hasattr(rate_limiter, "default_identifier_extractor")
