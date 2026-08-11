def invoice_total(lines: list[int], discount: int = 0) -> int:
    """Return a non-negative invoice total in cents."""
    return max(0, sum(lines) - discount)
