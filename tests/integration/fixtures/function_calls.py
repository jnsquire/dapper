# Script that calls a function — good for stepping and stack-trace tests
def add(a, b):  # line 2
    return a + b  # line 3


def multiply(a, b):  # line 6
    return a * b  # line 7


x = add(10, 20)  # line 10
y = multiply(x, 3)  # line 11
z = add(y, 1)  # line 12
