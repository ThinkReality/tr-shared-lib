from tr_shared.testing import describe_statements


def test_describe_numbers_the_first_line_of_each_statement() -> None:
    seen = ["SELECT a\nFROM t", "UPDATE t SET a = 1"]

    assert describe_statements(seen) == " 1. SELECT a\n 2. UPDATE t SET a = 1"


def test_describe_truncates_long_lines() -> None:
    assert describe_statements(["x" * 200]) == " 1. " + "x" * 110
