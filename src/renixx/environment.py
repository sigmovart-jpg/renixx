"""Runtime environment (scopes)."""
from .errors import RuntimeError as RTError


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

    def set(self, name, value, line=0, col=0):
        if name in self.values:
            if name in self.consts:
                raise RTError("Cannot reassign const '%s'" % name, line, col)
            self.values[name] = value
            return
        if self.parent is not None:
            self.parent.set(name, value, line, col)
            return
        raise RTError("Undefined variable '%s'" % name, line, col)

    def has(self, name):
        if name in self.values:
            return True
        if self.parent is not None:
            return self.parent.has(name)
        return False
