def discounted_total(subtotal: int, discount: int) -> int:
    return max(subtotal - discount, 0)