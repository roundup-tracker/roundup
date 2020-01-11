try:
    None < 0

    def NoneAndDictComparable(v):
        return v
except TypeError:
    # comparator to allow comparisons against None and dict
    # comparisons (these were allowed in Python 2, but aren't allowed
    # in Python 3 any more)
    class NoneAndDictComparable(object):
        def __init__(self, value):
            self.value = value

        def __cmp__(self, other):
            if not isinstance(other, self.__class__):
                raise TypeError('not comparable')

            if self.value == other.value:
                return 0

            elif self.value is None:
                return -1

            elif other.value is None:
                return 1

            elif type(self.value) == tuple and type(other.value) == tuple:
                for lhs, rhs in zip(self.value, other.value):
                    lhsCmp = NoneAndDictComparable(lhs)
                    rhsCmp = NoneAndDictComparable(rhs)
                    result = lhsCmp.__cmp__(rhsCmp)
                    if result != 0:
                        return result

                return len(self.value) - len(other.value)

            elif type(self.value) == dict and type(other.value) == dict:
                diff = len(self.value) - len(other.value)
                if diff == 0:
                    lhsItems = tuple(sorted(self.value.items(),
                                            key=NoneAndDictComparable))
                    rhsItems = tuple(sorted(other.value.items(),
                                            key=NoneAndDictComparable))
                    return -1 if NoneAndDictComparable(lhsItems) < NoneAndDictComparable(rhsItems) else 1
                else:
                    return diff

            elif self.value < other.value:
                return -1

            else:
                return 1

        def __eq__(self, other):
            return self.__cmp__(other) == 0

        def __ne__(self, other):
            return self.__cmp__(other) != 0

        def __lt__(self, other):
            return self.__cmp__(other) < 0

        def __le__(self, other):
            return self.__cmp__(other) <= 0

        def __ge__(self, other):
            return self.__cmp__(other) >= 0

        def __gt__(self, other):
            return self.__cmp__(other) > 0


def _test():
    Comp = NoneAndDictComparable

    assert Comp(None) < Comp(0)
    assert Comp(None) < Comp('')
    assert Comp(None) < Comp({})
    assert Comp((0, None)) < Comp((0, 0))
    assert not Comp(0) < Comp(None)
    assert not Comp('') < Comp(None)
    assert not Comp({}) < Comp(None)
    assert not Comp((0, 0)) < Comp((0, None))

    assert Comp((0, 0)) < Comp((0, 0, None))
    assert Comp((0, None, None)) < Comp((0, 0, 0))

    assert Comp(0) < Comp(1)
    assert Comp(1) > Comp(0)
    assert not Comp(1) < Comp(0)
    assert not Comp(0) > Comp(0)

    assert Comp({0: None}) < Comp({0: 0})
    assert Comp({0: 0}) < Comp({0: 1})

    assert Comp({0: 0}) == Comp({0: 0})
    assert Comp({0: 0}) != Comp({0: 1})
    assert Comp({0: 0, 1: 1}) > Comp({0: 1})
    assert Comp({0: 0, 1: 1}) < Comp({0: 0, 2: 2})


if __name__ == '__main__':
    _test()
