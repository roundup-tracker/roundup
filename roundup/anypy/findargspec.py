''' Wrapper for getargspec to support other callables and python 3 support

In python 3 just uses getfullargspec which handles regular functions
and classes with __call__ methods.
'''

try:
    # Python 3+
    from inspect import getfullargspec as getargspec
    findargspec = getargspec
except ImportError:
    # Python 2.5-2.7 modified from https://bugs.python.org/issue20828
    import inspect

    def findargspec(fn):
        if inspect.isfunction(fn) or inspect.ismethod(fn):
            inspectable = fn
        elif inspect.isclass(fn):
            inspectable = fn.__init__
        elif callable(fn):
            inspectable = fn.__call__
        else:
            inspectable = fn

        try:
            return inspect.getargspec(inspectable)
        except TypeError:
            raise
