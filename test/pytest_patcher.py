"""
The following code was taken from:

    https://github.com/pytest-dev/pytest/issues/568#issuecomment-216569420

to resolve a bug with using pytest.mark.skip(). Once the bug is resolved in
pytest this file can be removed along with all the wrapper mark_class()
references in the other test files.
"""
import types


def mark_class(marker):
    '''Workaround for https://github.com/pytest-dev/pytest/issues/568'''
    def copy_func(f):
        try:
            return types.FunctionType(f.__code__, f.__globals__,
                                      name=f.__name__, argdefs=f.__defaults__,
                                      closure=f.__closure__)
        except AttributeError:
            return types.FunctionType(f.func_code, f.func_globals,
                                      name=f.func_name,
                                      argdefs=f.func_defaults,
                                      closure=f.func_closure)

    def mark(cls):
        if isinstance(cls, types.FunctionType):
            return marker(copy_func(cls))

        for method in dir(cls):
            if method.startswith('test'):
                f = copy_func(getattr(cls, method))
                setattr(cls, method, marker(f))
        return cls
    return mark
