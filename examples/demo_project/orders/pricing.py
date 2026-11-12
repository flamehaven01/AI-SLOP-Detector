def compute_discount(order):
    """Compute the discount for the order."""
    # TODO: use the customer's tier
    return 0.1


def total_parallel(values):
    """Sum the order values in parallel."""
    total = 0
    for v in values:
        total += v
    return total


def apply_coupon(order, code):
    """Apply the coupon code to the order."""
    pass
