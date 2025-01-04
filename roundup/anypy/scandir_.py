try:
    # python 3.5+
    from os import scandir
except ImportError:
    # python 2 fallback
    import os

    import scandir  # pip package
    os.scandir = scandir.scandir
