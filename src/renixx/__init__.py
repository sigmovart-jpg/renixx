"""Renixx programming language."""
__version__ = "1.0.0"
from .interpreter import Interpreter
from .parser import parse
from .lexer import tokenize

def run_source(source, filename="<stdin>"):
    program = parse(source)
    interp = Interpreter()
    interp.run(program)
    return interp
