"""Test corpus for placeholder patterns."""


# pass_placeholder - Should trigger HIGH
def not_implemented_yet():
    """This function is not implemented."""
    pass  # [!] Empty function


# todo_comment - Should trigger MEDIUM
def needs_work():
    # TODO: implement this properly  # [!]
    return None


# fixme_comment - Should trigger MEDIUM
def has_bug():
    # FIXME: this breaks with negative numbers  # [!]
    return value * 2


# hack_comment - Should trigger HIGH
def quick_fix():
    # HACK: temporary workaround  # [!]
    return value + 1


# ellipsis_placeholder - Should trigger HIGH
def stub_function():
    """Function stub."""
    ...  # [!] Empty function


# Multiple TODOs
def lots_of_work():
    # TODO: validate input  # [!]
    data = get_data()

    # TODO: process data  # [!]
    result = data

    # TODO: return formatted result  # [!]
    return result


# GOOD EXAMPLES (should NOT trigger)
def implemented_function():
    """This function is implemented."""
    if value < 0:
        raise ValueError("Must be positive")
    return value * 2


def with_explanation():
    # This uses a greedy algorithm for performance
    # It's O(n log n) instead of O(n^2)
    return sorted(items, key=lambda x: x.score)
