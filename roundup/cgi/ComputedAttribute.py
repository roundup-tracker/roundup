class ComputedAttribute:
    def __init__(self, callable, level):
        self.callable = callable
        self.level = level
    def __of__(self, *args):
        if self.level > 0:
            return self.callable
        if isinstance(self.callable, type('')):
            return getattr(args[0], self.callable)
        return self.callable(*args)

