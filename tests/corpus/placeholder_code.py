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


# ABC REGRESSION — none of the below should trigger any placeholder pattern
from abc import ABC, abstractmethod
from typing import Optional


class IntentionalInterface(ABC):
    @abstractmethod
    def method_one(self) -> None: ...  # ellipsis_placeholder must NOT fire

    @abstractmethod
    def method_two(self) -> Optional[str]: ...  # ellipsis_placeholder must NOT fire

    @abstractmethod
    def method_three(self) -> int: ...  # ellipsis_placeholder must NOT fire


class NullImpl(IntentionalInterface):
    def method_one(self) -> None:
        pass  # pass_placeholder must NOT fire (concrete impl of abstract)

    def method_two(self) -> Optional[str]:
        return None  # return_none_placeholder must NOT fire (Optional annotation)

    def method_three(self) -> int:
        return 0
