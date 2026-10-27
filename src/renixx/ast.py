"""Abstract Syntax Tree nodes for the Renixx language."""
from dataclasses import dataclass, field
from typing import List, Optional, Any


@dataclass
class Node:
    line: int = 0
    col: int = 0


# ---- Expressions ----
@dataclass
class Expr(Node):
    pass


@dataclass
class Literal(Expr):
    value: Any = None

@dataclass
class InterpolatedString(Expr):
    parts: list = field(default_factory=list)  # list of ("text", str) or ("expr", Expr)


@dataclass
class Identifier(Expr):
    name: str = ""


@dataclass
class UnaryOp(Expr):
    op: str = ""
    operand: Expr = None


@dataclass
class BinaryOp(Expr):
    op: str = ""
    left: Expr = None
    right: Expr = None


@dataclass
class Assign(Expr):
    target: Expr = None
    value: Expr = None
    op: str = "="  # =, +=, -=, etc.


@dataclass
class Call(Expr):
    callee: Expr = None
    args: List[Expr] = field(default_factory=list)
    kwargs: List = field(default_factory=list)  # list of (name, expr)


@dataclass
class Index(Expr):
    obj: Expr = None
    index: Expr = None

@dataclass
class Slice(Expr):
    obj: Expr = None
    start: Optional[Expr] = None
    stop: Optional[Expr] = None
    step: Optional[Expr] = None


@dataclass
class Member(Expr):
    obj: Expr = None
    name: str = ""


@dataclass
class ListLiteral(Expr):
    elements: List[Expr] = field(default_factory=list)

@dataclass
class Spread(Expr):
    value: Expr = None

@dataclass
class ListComp(Expr):
    expr: Expr = None
    var: str = ""
    iterable: Expr = None
    cond: Optional[Expr] = None

@dataclass
class DictComp(Expr):
    key: Expr = None
    val: Expr = None
    var: str = ""
    iterable: Expr = None
    cond: Optional[Expr] = None


@dataclass
class DictLiteral(Expr):
    pairs: List = field(default_factory=list)  # list of (key_expr, val_expr)


@dataclass
class FunctionExpr(Expr):
    params: List = field(default_factory=list)  # list of (name, default_expr or None, rest bool)
    body: "Block" = None
    name: Optional[str] = None


@dataclass
class Lambda(Expr):
    params: List = field(default_factory=list)
    body: Expr = None  # single expression


@dataclass
class NewExpr(Expr):
    class_name: str = ""
    args: List[Expr] = field(default_factory=list)
    class_name_col: int = 0


@dataclass
class AwaitExpr(Expr):  # placeholder
    value: Expr = None


@dataclass
class Ternary(Expr):
    cond: Expr = None
    then_expr: Expr = None
    else_expr: Expr = None


@dataclass
class RangeExpr(Expr):
    start: Expr = None
    stop: Expr = None
    step: Optional[Expr] = None
    inclusive: bool = False


# ---- Statements ----
@dataclass
class Stmt(Node):
    pass


@dataclass
class Block(Stmt):
    statements: List[Stmt] = field(default_factory=list)


@dataclass
class ExprStmt(Stmt):
    expr: Expr = None


@dataclass
class LetStmt(Stmt):
    name: str = ""
    value: Optional[Expr] = None
    mutable: bool = True  # let vs const
    type_annot: Optional[str] = None
    name_col: int = 0
    type_annot_col: int = 0

@dataclass
class DestructureStmt(Stmt):
    kind: str = "list"  # list or dict
    names: List[str] = field(default_factory=list)
    value: Optional[Expr] = None
    mutable: bool = True
    name_col: int = 0


@dataclass
class ConstStmt(LetStmt):
    pass


@dataclass
class FnDecl(Stmt):
    name: str = ""
    params: List = field(default_factory=list)
    body: Block = None
    decorators: List[str] = field(default_factory=list)
    return_type: Optional[str] = None
    name_col: int = 0
    return_type_col: int = 0
    return_type_line: int = 0


@dataclass
class ClassDecl(Stmt):
    name: str = ""
    superclass: Optional[str] = None
    name_col: int = 0
    methods: List[FnDecl] = field(default_factory=list)
    fields: List[LetStmt] = field(default_factory=list)


@dataclass
class IfStmt(Stmt):
    cond: Expr = None
    then_branch: Block = None
    else_branch: Optional[Stmt] = None


@dataclass
class WhileStmt(Stmt):
    cond: Expr = None
    body: Block = None


@dataclass
class ForStmt(Stmt):
    # for x in iterable  OR  for init; cond; step
    var: Optional[str] = None
    iterable: Optional[Expr] = None
    init: Optional[Stmt] = None
    cond: Optional[Expr] = None
    step: Optional[Expr] = None
    body: Block = None


@dataclass
class MatchStmt(Stmt):
    expr: Expr = None
    cases: List = field(default_factory=list)  # list of (pattern_expr_or_None, guard, body)


@dataclass
class TryStmt(Stmt):
    try_block: Block = None
    catch_var: Optional[str] = None
    catch_block: Optional[Block] = None
    finally_block: Optional[Block] = None


@dataclass
class ReturnStmt(Stmt):
    value: Optional[Expr] = None


@dataclass
class BreakStmt(Stmt):
    pass


@dataclass
class ContinueStmt(Stmt):
    pass


@dataclass
class ThrowStmt(Stmt):
    value: Expr = None


@dataclass
class ImportStmt(Stmt):
    path: str = ""
    alias: Optional[str] = None
    names: Optional[List[str]] = None  # for `from x import a, b`


@dataclass
class Program(Node):
    statements: List[Stmt] = field(default_factory=list)
