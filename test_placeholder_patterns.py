"""Test file for placeholder pattern detection."""


def empty_function():
    """This function does nothing."""
    pass


def ellipsis_function():
    """This uses ellipsis."""
    ...


def not_implemented_function():
    """This raises NotImplementedError."""
    raise NotImplementedError("This needs to be implemented")


def return_none_function():
    """This just returns None."""
    return None


def function_with_todo():
    # TODO: Implement this function
    print("Temporary implementation")


def function_with_fixme():
    # FIXME: This is broken
    result = 1 / 0
    return result


def function_with_hack():
    # HACK: This is a workaround
    return "quick fix"


def function_with_empty_except():
    """This has empty exception handler."""
    try:
        risky_operation()
    except:
        pass  # Silently ignore errors


class InterfaceOnlyClass:
    """This class has only placeholder methods."""

    def method1(self):
        pass

    def method2(self):
        ...

    def method3(self):
        raise NotImplementedError

    def method4(self):
        return None
