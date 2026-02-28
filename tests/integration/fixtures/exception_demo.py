# Script that raises an exception — good for exception breakpoint tests
def divide(a, b):
    return a / b  # line 3


try:
    x = divide(10, 2)  # line 6 — succeeds
    y = divide(10, 0)  # line 7 — raises ZeroDivisionError
except ZeroDivisionError:
    y = -1  # line 9
