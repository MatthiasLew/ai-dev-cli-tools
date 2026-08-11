from workspaces.catalog.src.catalog import available_skus


def test_available_skus_ignores_empty_stock() -> None:
    assert available_skus({"B": 2, "A": 0, "C": 1}) == ["B", "C"]
