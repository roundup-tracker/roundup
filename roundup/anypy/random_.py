try:
    from secrets import choice, randbelow, token_bytes

    def seed(v=None):
        pass

    is_weak = False
except ImportError:
    import os as _os
    import random as _random

    # prefer to use SystemRandom if it is available
    if hasattr(_random, 'SystemRandom'):
        def seed(v=None):
            pass

        _r = _random.SystemRandom()
        is_weak = False
    else:
        # don't completely throw away the existing state, but add some
        # more random state to the existing state
        def seed(v=None):
            import os, time
            _r.seed((_r.getstate(),
                     v,
                     hasattr(os, 'getpid') and os.getpid(),
                     time.time()))

        # create our own instance so we don't mess with the global
        # random number generator
        _r = _random.Random()
        seed()
        is_weak = True

    choice = _r.choice

    def randbelow(i):
        return _r.randint(0, i - 1)

    if hasattr(_os, 'urandom'):
        def token_bytes(l):
            return _os.urandom(l)
    else:
        def token_bytes(l):
            _bchr = chr if str == bytes else lambda x: bytes((x,))
            return b''.join([_bchr(_r.getrandbits(8)) for i in range(l)])
