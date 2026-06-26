"""PaginationData.total_pages behaviour — optional + auto-computed."""

from tr_shared.schemas.responses import PaginationData


def test_total_pages_computed_when_omitted():
    page = PaginationData(items=[], total=100, page=1, page_size=20)
    assert page.total_pages == 5


def test_total_pages_zero_when_empty():
    page = PaginationData(items=[], total=0, page=1, page_size=20)
    assert page.total_pages == 0


def test_total_pages_preserved_when_correct_value_passed():
    page = PaginationData(items=[], total=100, page=1, page_size=20, total_pages=5)
    assert page.total_pages == 5


def test_total_pages_corrected_when_wrong_value_passed():
    page = PaginationData(items=[], total=100, page=1, page_size=20, total_pages=99)
    assert page.total_pages == 5
