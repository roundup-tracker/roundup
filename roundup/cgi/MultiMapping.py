class MultiMapping:
    def __init__(self, *stores):
        self.stores = list(stores)
        self.stores.reverse()

    def __getitem__(self, key):
        for store in self.stores:
            if store.has_key(key):
                return store[key]
        raise KeyError, key

    def __setitem__(self, key, val):
        self.stores[0][key] = val

    _marker = []

    def get(self, key, default=_marker):
        for store in self.stores:
            if store.has_key(key):
                return store[key]
        if default is self._marker:
            raise KeyError, key
        return default

    def __len__(self):
        return len(self.items())

    def has_key(self, key):
        for store in self.stores:
            if store.has_key(key):
                return 1
        return 0

    def push(self, store):
        self.stores = [store] + self.stores

    def pop(self):
        if not len(self.stores):
            return None
        store, self.stores = self.stores[0], self.stores[1:]
        return store

    def keys(self):
        return [ _[0] for _ in self.items() ]

    def values(self):
        return [ _[1] for _ in self.items() ]

    def copy(self):
       copy = MultiMapping()
       copy.stores = [_.copy() for _ in self.stores]
       return copy

    def items(self):
        l = []
        seen = {}
        for store in self.stores:
            for k, v in store.items():
                if not seen.has_key(k):
                    l.append((k, v))
                    seen[k] = 1
        return l

