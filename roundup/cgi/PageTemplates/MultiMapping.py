import operator

class MultiMapping:
    def __init__(self, *stores):
        self.stores = list(stores)
    def __getitem__(self, key):
        for store in self.stores:
            if key in store:
                return store[key]
        raise KeyError(key)
    _marker = []
    def get(self, key, default=_marker):
        for store in self.stores:
            if key in store:
                return store[key]
        if default is self._marker:
            raise KeyError(key)
        return default
    def __len__(self):
        return sum([len(x) for x in self.stores])
    def push(self, store):
        self.stores.append(store)
    def pop(self):
        return self.stores.pop()
    def items(self):
        l = []
        for store in self.stores:
            l = l + list(store.items())
        return l
