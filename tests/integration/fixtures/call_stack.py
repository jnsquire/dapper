# Script with multiple functions at different depths — good for stack depth tests
def level3():
    return "deep"  # line 3


def level2():
    return level3()  # line 7


def level1():
    return level2()  # line 10


result = level1()  # line 12
