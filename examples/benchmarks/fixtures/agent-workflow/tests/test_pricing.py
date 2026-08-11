from src.pricing import calculate_total


def test_calculate_total() -> None:
    assert calculate_total(1000, 230) == 1230