from workspaces.billing.src.billing import invoice_total


def test_invoice_total_applies_discount() -> None:
    assert invoice_total([1200, 800], discount=250) == 1750
