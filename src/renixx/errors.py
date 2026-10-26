"""Error types for the Renixx language."""
class RenixxError(Exception):
    def __init__(self, message, line=0, col=0, kind="Error"):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col
        self.kind = kind

    def __str__(self):
        loc = f" (line {self.line})" if self.line else ""
        return f"{self.kind}{loc}: {self.message}"


class LexError(RenixxError):
    def __init__(self, message, line=0, col=0):
        super().__init__(message, line, col, "LexError")


class ParseError(RenixxError):
    def __init__(self, message, line=0, col=0):
        super().__init__(message, line, col, "ParseError")


_CURRENT_STACK = []

def set_current_stack(stack):
    global _CURRENT_STACK
    _CURRENT_STACK = stack

class RuntimeError(RenixxError):
    def __init__(self, message, line=0, col=0, stack=None):
        super().__init__(message, line, col, "RuntimeError")
        if stack is None:
            stack = list(_CURRENT_STACK)
        self.stack = stack


class ReturnValue(Exception):
    """Control-flow exception for return statements."""
    def __init__(self, value):
        self.value = value


class BreakSignal(Exception):
    pass


class ContinueSignal(Exception):
    pass
