"""Test corpus for structural patterns - intentionally bad code."""


# bare_except - Should trigger CRITICAL
def bad_exception_handling():
    try:
        risky_operation()
    except:  # [!] Catches SystemExit, KeyboardInterrupt
        pass


# mutable_default_arg - Should trigger CRITICAL
def bad_function(items=[]):  # [!] Shared state bug
    items.append(1)
    return items


# star_import - Should trigger HIGH
from os import *  # [!] Pollutes namespace


# global_statement - Should trigger HIGH
global_var = 0


def bad_global_usage():
    global global_var  # [!] Makes testing harder
    global_var += 1


# exec_eval_usage - Should trigger CRITICAL
def dangerous_code(user_input):
    exec(user_input)  # [!] Security risk
    result = eval(user_input)  # [!] Security risk
    return result


# assert_in_production - Should trigger MEDIUM
def check_value(x):
    assert x > 0  # [!] Removed with -O flag
    return x * 2


# GOOD EXAMPLES (should NOT trigger)
def good_exception_handling():
    try:
        risky_operation()
    except ValueError as e:  # [+] Specific exception
        logger.error(f"Error: {e}")


def good_function(items=None):  # [+] None as default
    if items is None:
        items = []
    items.append(1)
    return items


from os import path, environ  # [+] Specific imports


def good_function_without_global(value):  # [+] Pass as argument
    return value + 1
