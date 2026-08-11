def available_skus(stock: dict[str, int]) -> list[str]:
    """Return sorted SKUs that currently have stock."""
    return sorted(sku for sku, quantity in stock.items() if quantity > 0)
