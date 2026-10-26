"""Runtime environment (scopes)."""
class Environment:
    def __init__(self, parent=None):
        self.values = {}
        self.consts = set()
        self.parent = parent

    def define(self, name, value, mutable=True):
        self.values[name] = value
        if not mutable:
            self.consts.add(name)

    def get(self, name):
        if name in self.values:
            return self.values[name]
        if self.parent is not None:
            return self.parent.get(name)
        raise KeyError(name)

    def set(self, name, value):
        if name in self.values:
            if name in self.consts:
                raise Exception("Cannot reassign const '%s'" % name)
            self.values[name] = value
            return
        if self.parent is not None:
            self.parent.set(name, value)
            return
        raise Exception("Undefined variable '%s'" % name)

    def has(self, name):
        if name in self.values:
            return True
        if self.parent is not None:
            return self.parent.has(name)
        return False
