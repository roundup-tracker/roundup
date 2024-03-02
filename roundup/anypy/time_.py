try:
    # Python 3+
    from time import perf_counter
except (ImportError, AttributeError):
    # Python 2.5-2.7
    from time import clock as perf_counter  # noqa: F401
