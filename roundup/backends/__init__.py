__all__ = []

try:
    import back_anydbm
    anydbm = back_anydbm
    del back_anydbm
    __all__.append('anydbm')
except:
    pass

try:
    import back_bsddb
    bsddb = back_bsddb
    del back_bsddb
    __all__.append('bsddb')
except:
    pass

try:
    import back_bsddb3
    bsddb3 = back_bsddb3
    del back_bsddb3
    __all__.append('bsddb3')
except:
    pass

