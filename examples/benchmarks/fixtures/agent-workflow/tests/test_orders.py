from src.orders import discounted_total


def test_discounted_total() -> None:
    assert discounted_total(1000, 100) == 900