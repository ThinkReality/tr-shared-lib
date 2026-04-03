"""Tests for normalize_path — pure function, no mocking needed."""

import pytest

from tr_shared.monitoring.path_normalizer import normalize_path


class TestNormalizePath:
    def test_static_path_unchanged(self):
        assert normalize_path("/health") == "/health"

    def test_root_unchanged(self):
        assert normalize_path("/") == "/"

    def test_api_prefix_unchanged(self):
        assert normalize_path("/api/v1/listings") == "/api/v1/listings"

    def test_uuid_normalized(self):
        result = normalize_path("/api/v1/users/550e8400-e29b-41d4-a716-446655440000")
        assert result == "/api/v1/users/{id}"

    def test_uuid_case_insensitive(self):
        result = normalize_path("/api/v1/users/550E8400-E29B-41D4-A716-446655440000")
        assert result == "/api/v1/users/{id}"

    def test_numeric_id_normalized(self):
        result = normalize_path("/api/v1/orders/42/items")
        assert result == "/api/v1/orders/{id}/items"

    def test_multiple_numeric_ids(self):
        result = normalize_path("/users/1/posts/99")
        assert result == "/users/{id}/posts/{id}"

    def test_multiple_uuids(self):
        result = normalize_path(
            "/a/550e8400-e29b-41d4-a716-446655440000/b/550e8400-e29b-41d4-a716-446655440001"
        )
        assert result == "/a/{id}/b/{id}"

    def test_trailing_segment_after_uuid(self):
        result = normalize_path("/users/550e8400-e29b-41d4-a716-446655440000/profile")
        assert result == "/users/{id}/profile"

    def test_numeric_at_end_normalized(self):
        result = normalize_path("/api/v1/listings/123")
        assert result == "/api/v1/listings/{id}"

    def test_mixed_uuid_and_numeric(self):
        path = "/users/550e8400-e29b-41d4-a716-446655440000/orders/42"
        result = normalize_path(path)
        assert "{id}" in result
        assert "550e8400" not in result
        assert "42" not in result

    def test_docs_path_unchanged(self):
        assert normalize_path("/docs") == "/docs"

    def test_empty_path(self):
        assert normalize_path("") == ""
