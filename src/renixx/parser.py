"""Parser for the Renixx language."""
from .lexer import tokenize
from .errors import ParseError
from .ast import *

class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0
        self.allow_lambda = True

    def peek(self, offset=0):
        i = self.pos + offset
        if i < len(self.tokens):
            return self.tokens[i]
        return self.tokens[-1]  # EOF

    def current(self):
        return self.peek(0)

    def advance(self):
        tok = self.current()
        self.pos += 1
        return tok

    def skip_newlines(self):
        while self.current().type == "NEWLINE" or (self.current().type == "OP" and self.current().value == ";"):
            self.advance()

    def expect(self, type_, value=None):
        tok = self.current()
        if tok.type != type_ or (value is not None and tok.value != value):
            raise ParseError("Expected %s%s but got %s %r" % (type_, (" "+repr(value)) if value else "", tok.type, tok.value), tok.line, tok.col)
        return self.advance()

    def match(self, type_, value=None):
        tok = self.current()
        if tok.type == type_ and (value is None or tok.value == value):
            self.advance()
            return tok
        return None

    def at_end(self):
        return self.current().type == "EOF"

    def parse(self):
        stmts = []
        self.skip_newlines()
        while not self.at_end():
            stmt = self.parse_statement()
            if stmt is not None:
                stmts.append(stmt)
            self.skip_newlines()
        return Program(statements=stmts, line=1)

    # ---- statements ----
    def parse_statement(self):
        self.skip_newlines()
        tok = self.current()
        if tok.type == "EOF":
            return None
        if tok.type == "KEYWORD":
            kw = tok.value
            if kw == "let":
                return self.parse_let(False)
            if kw == "const":
                return self.parse_let(True)
            if kw == "fn":
                return self.parse_fn_decl()
            if kw == "class":
                return self.parse_class()
            if kw == "if":
                return self.parse_if()
            if kw == "while":
                return self.parse_while()
            if kw == "for":
                return self.parse_for()
            if kw == "match":
                return self.parse_match()
            if kw == "try":
                return self.parse_try()
            if kw == "return":
                return self.parse_return()
            if kw == "throw":
                return self.parse_throw()
            if kw == "break":
                self.advance()
                return BreakStmt(line=tok.line)
            if kw == "continue":
                self.advance()
                return ContinueStmt(line=tok.line)
            if kw == "import":
                return self.parse_import()
            if kw == "export":
                self.advance()
                s = self.parse_statement()
                return s
            if kw in ("from",):
                return self.parse_import_from()
        # expression statement
        expr = self.parse_expression()
        # optional trailing semicolon/newline handled by caller
        return ExprStmt(expr=expr, line=expr.line)

    def parse_type_annotation(self):
        if self.current().type != "IDENT":
            raise ParseError("Expected type name", self.current().line, self.current().col)
        col = self.current().col
        name = self.advance().value
        if self.current().type == "LBRACKET":
            self.advance()
            self.skip_newlines()
            args = [self.parse_type_annotation()[0]]
            self.skip_newlines()
            while self.current().type == "OP" and self.current().value == ",":
                self.advance()
                self.skip_newlines()
                arg_name, _ = self.parse_type_annotation()
                args.append(arg_name)
                self.skip_newlines()
            self.expect("RBRACKET", "]")
            annot = name + "[" + ", ".join(args) + "]"
            return annot, col
        return name, col

    def parse_let(self, is_const):
        kw_tok = self.advance()  # let/const
        # destructuring: let [a, b] = expr  or  let {a, b} = expr
        if self.current().type == "LBRACKET":
            self.advance()
            names = []
            name_col = self.current().col if self.current().type == "IDENT" else 0
            while self.current().type != "RBRACKET":
                self.skip_newlines()
                if self.current().type != "IDENT":
                    raise ParseError("Expected name in destructure", self.current().line)
                names.append(self.advance().value)
                self.skip_newlines()
                if self.current().type == "OP" and self.current().value == ",":
                    self.advance()
                    continue
                break
            self.expect("RBRACKET", "]")
            if not self.match("OP", "="):
                raise ParseError("Expected '=' in destructure", kw_tok.line)
            value = self.parse_expression()
            return DestructureStmt(kind="list", names=names, value=value, mutable=not is_const, line=kw_tok.line, name_col=name_col)
        if self.current().type == "LBRACE":
            self.advance()
            names = []
            name_col = self.current().col if self.current().type == "IDENT" else 0
            while self.current().type != "RBRACE":
                self.skip_newlines()
                if self.current().type != "IDENT":
                    raise ParseError("Expected name in destructure", self.current().line)
                names.append(self.advance().value)
                self.skip_newlines()
                if self.current().type == "OP" and self.current().value == ",":
                    self.advance()
                    continue
                break
            self.expect("RBRACE", "}")
            if not self.match("OP", "="):
                raise ParseError("Expected '=' in destructure", kw_tok.line)
            value = self.parse_expression()
            return DestructureStmt(kind="dict", names=names, value=value, mutable=not is_const, line=kw_tok.line, name_col=name_col)
        if self.current().type != "IDENT":
            raise ParseError("Expected variable name after let/const", kw_tok.line)
        name_col = self.current().col
        name = self.advance().value
        type_annot = None
        type_annot_col = 0
        if self.current().type == "OP" and self.current().value == ":":
            self.advance()
            self.skip_newlines()
            if self.current().type == "IDENT":
                type_annot, type_annot_col = self.parse_type_annotation()
        value = None
        if self.match("OP", "="):
            value = self.parse_expression()
        node = LetStmt(name=name, value=value, mutable=not is_const, type_annot=type_annot, line=kw_tok.line, name_col=name_col, type_annot_col=type_annot_col)
        if is_const:
            node = ConstStmt(name=name, value=value, mutable=False, line=kw_tok.line, name_col=name_col, type_annot=type_annot, type_annot_col=type_annot_col)
        return node

    def parse_fn_decl(self):
        kw = self.advance()  # fn
        name = None
        name_col = 0
        if self.current().type == "IDENT":
            name_col = self.current().col
            name = self.advance().value
        params = self.parse_params()
        self.skip_newlines()
        return_type = None
        return_type_col = 0
        return_type_line = 0
        if self.current().type == "OP" and self.current().value == "->":
            self.advance()
            self.skip_newlines()
            if self.current().type == "IDENT":
                return_type_line = self.current().line
                return_type, return_type_col = self.parse_type_annotation()
        self.skip_newlines()
        body = self.parse_block()
        return FnDecl(name=name, params=params, body=body, return_type=return_type, line=kw.line, name_col=name_col, return_type_col=return_type_col, return_type_line=return_type_line)

    def parse_params(self):
        params = []
        if not self.match("LPAREN", "("):
            # allow fn f x => ...? no, require parens
            raise ParseError("Expected '(' after function name", self.current().line)
        self.skip_newlines()
        while self.current().type != "RPAREN":
            self.skip_newlines()
            if self.current().type == "OP" and self.current().value == "...":
                self.advance()
                if self.current().type != "IDENT":
                    raise ParseError("Expected rest param name", self.current().line)
                pname = self.advance().value
                annot = None
                annot_col = 0
                annot_line = 0
                if self.current().type == "OP" and self.current().value == ":":
                    self.advance()
                    self.skip_newlines()
                    if self.current().type == "IDENT":
                        annot_line = self.current().line
                        annot, annot_col = self.parse_type_annotation()
                params.append((pname, None, True, annot, annot_col, annot_line))
            elif self.current().type == "IDENT":
                pname = self.advance().value
                annot = None
                annot_col = 0
                annot_line = 0
                if self.current().type == "OP" and self.current().value == ":":
                    self.advance()
                    self.skip_newlines()
                    if self.current().type == "IDENT":
                        annot_line = self.current().line
                        annot, annot_col = self.parse_type_annotation()
                default = None
                if self.match("OP", "="):
                    default = self.parse_expression()
                params.append((pname, default, False, annot, annot_col, annot_line))
            else:
                raise ParseError("Expected parameter name", self.current().line)
            self.skip_newlines()
            if self.current().type == "OP" and self.current().value == ",":
                self.advance()
                self.skip_newlines()
                continue
            if self.current().type == "RPAREN":
                break
            raise ParseError("Expected ',' or ')'", self.current().line)
        self.expect("RPAREN", ")")
        return params

    def parse_block(self):
        if self.current().type == "LBRACE":
            brace = self.advance()
            stmts = []
            self.skip_newlines()
            while self.current().type != "RBRACE" and not self.at_end():
                s = self.parse_statement()
                if s is not None:
                    stmts.append(s)
                self.skip_newlines()
            self.expect("RBRACE", "}")
            return Block(statements=stmts, line=brace.line)
        # single statement block? require braces
        raise ParseError("Expected '{'", self.current().line)

    def parse_class(self):
        kw = self.advance()  # class
        if self.current().type != "IDENT":
            raise ParseError("Expected class name", kw.line)
        name_col = self.current().col
        name = self.advance().value
        superclass = None
        if self.current().type == "KEYWORD" and self.current().value == "extends":
            self.advance()
            if self.current().type != "IDENT":
                raise ParseError("Expected superclass name", self.current().line)
            superclass = self.advance().value
        self.skip_newlines()
        body = self.parse_block()
        methods = []
        fields = []
        for s in body.statements:
            if isinstance(s, FnDecl):
                methods.append(s)
            elif isinstance(s, LetStmt):
                fields.append(s)
            else:
                # wrap? keep as method? ignore
                pass
        return ClassDecl(name=name, superclass=superclass, methods=methods, fields=fields, line=kw.line, name_col=name_col)

    def parse_if(self):
        kw = self.advance()
        cond = self.parse_expression()
        self.skip_newlines()
        then_b = self.parse_block()
        else_b = None
        self.skip_newlines()
        if self.current().type == "KEYWORD" and self.current().value == "else":
            self.advance()
            self.skip_newlines()
            if self.current().type == "KEYWORD" and self.current().value == "if":
                else_b = self.parse_if()
            else:
                else_b = self.parse_block()
        return IfStmt(cond=cond, then_branch=then_b, else_branch=else_b, line=kw.line)

    def parse_while(self):
        kw = self.advance()
        cond = self.parse_expression()
        self.skip_newlines()
        body = self.parse_block()
        return WhileStmt(cond=cond, body=body, line=kw.line)

    def parse_for(self):
        kw = self.advance()
        self.skip_newlines()
        # for x in iterable
        # detect: parse an expression; if next is 'in' keyword -> for-in
        # We'll parse a primary/ident
        if self.current().type == "IDENT" and self.peek(1).type == "KEYWORD" and self.peek(1).value == "in":
            var = self.advance().value
            self.advance()  # in
            iterable = self.parse_expression()
            self.skip_newlines()
            body = self.parse_block()
            return ForStmt(var=var, iterable=iterable, body=body, line=kw.line)
        # C-style: for (init; cond; step)
        # allow optional parens
        has_paren = self.match("LPAREN", "(") is not None
        init = None
        if self.current().type != "OP" or self.current().value != ";":
            # could be let/var or expr
            if self.current().type == "KEYWORD" and self.current().value in ("let", "const"):
                init = self.parse_let(self.current().value == "const")
            else:
                e = self.parse_expression()
                init = ExprStmt(expr=e, line=e.line)
        self.skip_newlines()
        if self.match("OP", ";") is None and not (self.current().type == "OP" and self.current().value == ";"):
            pass
        self.match("OP", ";")
        cond = None
        if not (self.current().type == "OP" and self.current().value == ";"):
            cond = self.parse_expression()
        self.match("OP", ";")
        step = None
        if not (self.current().type == "RPAREN" or self.current().type == "LBRACE"):
            step = self.parse_expression()
        if has_paren:
            self.match("RPAREN", ")")
        self.skip_newlines()
        body = self.parse_block()
        return ForStmt(init=init, cond=cond, step=step, body=body, line=kw.line)

    def parse_match(self):
        kw = self.advance()
        expr = self.parse_expression()
        self.skip_newlines()
        self.expect("LBRACE", "{")
        cases = []
        self.skip_newlines()
        while self.current().type != "RBRACE" and not self.at_end():
            # pattern
            if self.current().type == "KEYWORD" and self.current().value == "default":
                self.advance()
                self.skip_newlines()
                # expect =>
                if self.current().type == "OP" and self.current().value == "=>":
                    self.advance()
                else:
                    # maybe :
                    pass
                self.skip_newlines()
                body = self.parse_block() if self.current().type == "LBRACE" else self.parse_statement()
                cases.append((None, None, body))
                self.skip_newlines()
                # optional comma
                self.match("OP", ",")
                self.skip_newlines()
                continue
            # pattern expr
            self.allow_lambda = False
            pat = self.parse_expression()
            self.allow_lambda = True
            guard = None
            if self.current().type == "KEYWORD" and self.current().value == "if":
                self.advance()
                saved_pos = self.pos
                saved_allow = self.allow_lambda
                try:
                    self.allow_lambda = True
                    guard = self.parse_expression()
                    if not (self.current().type == "OP" and self.current().value in ("=>", "->")):
                        # lambda consumed the arrow; retry without lambda
                        raise ParseError("guard consumed arrow", self.current().line, self.current().col)
                except ParseError:
                    self.pos = saved_pos
                    self.allow_lambda = False
                    guard = self.parse_expression()
                    self.allow_lambda = saved_allow
                else:
                    self.allow_lambda = saved_allow
            self.skip_newlines()
            if self.current().type == "OP" and self.current().value in ("=>", "->"):
                self.advance()
            self.skip_newlines()
            if self.current().type == "LBRACE":
                body = self.parse_block()
            else:
                body = self.parse_statement()
            cases.append((pat, guard, body))
            self.skip_newlines()
            self.match("OP", ",")
            self.skip_newlines()
        self.expect("RBRACE", "}")
        return MatchStmt(expr=expr, cases=cases, line=kw.line)

    def parse_try(self):
        kw = self.advance()
        self.skip_newlines()
        try_block = self.parse_block()
        catch_var = None
        catch_block = None
        finally_block = None
        self.skip_newlines()
        if self.current().type == "KEYWORD" and self.current().value == "catch":
            self.advance()
            if self.current().type == "IDENT":
                catch_var = self.advance().value
            elif self.match("LPAREN", "("):
                if self.current().type == "IDENT":
                    catch_var = self.advance().value
                self.match("RPAREN", ")")
            self.skip_newlines()
            catch_block = self.parse_block()
            self.skip_newlines()
        if self.current().type == "KEYWORD" and self.current().value == "finally":
            self.advance()
            self.skip_newlines()
            finally_block = self.parse_block()
        return TryStmt(try_block=try_block, catch_var=catch_var, catch_block=catch_block, finally_block=finally_block, line=kw.line)

    def parse_return(self):
        kw = self.advance()
        value = None
        if not (self.current().type == "NEWLINE" or self.current().type == "RBRACE" or self.current().type == "EOF" or (self.current().type == "OP" and self.current().value == ";")):
            value = self.parse_expression()
        return ReturnStmt(value=value, line=kw.line)

    def parse_throw(self):
        kw = self.advance()
        val = self.parse_expression()
        return ThrowStmt(value=val, line=kw.line)

    def parse_import(self):
        kw = self.advance()
        # import "path"
        # import "path" as alias
        # from "path" import a, b
        # handle 'from' already consumed? parse_import called on 'import' keyword.
        # Case: import "path" ...
        if self.current().type == "STRING":
            path = self.advance().value
            alias = None
            if self.current().type == "KEYWORD" and self.current().value == "as":
                self.advance()
                if self.current().type != "IDENT":
                    raise ParseError("Expected alias name", self.current().line)
                alias = self.advance().value
            return ImportStmt(path=path, alias=alias, line=kw.line)
        # import * from? skip
        # maybe 'import name from "path"' (JS style) - support: import X from "path"
        if self.current().type == "IDENT":
            # could be `import name from "path"`
            name = self.advance().value
            if self.current().type == "KEYWORD" and self.current().value == "from":
                self.advance()
                if self.current().type != "STRING":
                    raise ParseError("Expected string path", self.current().line)
                path = self.advance().value
                return ImportStmt(path=path, alias=name, line=kw.line)
        raise ParseError("Invalid import statement", kw.line)

    def parse_import_from(self):
        # from "path" import a, b
        kw = self.advance()  # from
        if self.current().type != "STRING":
            raise ParseError("Expected string path after from", kw.line)
        path = self.advance().value
        if not (self.current().type == "KEYWORD" and self.current().value == "import"):
            raise ParseError("Expected 'import'", self.current().line)
        self.advance()
        names = []
        while True:
            self.skip_newlines()
            if self.current().type == "OP" and self.current().value == "*":
                self.advance()
                names = None
                break
            if self.current().type != "IDENT":
                break
            names.append(self.advance().value)
            if self.current().type == "OP" and self.current().value == ",":
                self.advance()
                continue
            break
        return ImportStmt(path=path, names=names, line=kw.line)

    # ---- expressions ----
    def parse_expression(self):
        return self.parse_assignment()

    def parse_assignment(self):
        expr = self.parse_ternary()
        # assignment operators
        if self.current().type == "OP" and self.current().value in ("=", "+=", "-=", "*=", "/=", "%="):
            op = self.current().value
            self.advance()
            value = self.parse_assignment()
            return Assign(target=expr, value=value, op=op, line=expr.line)
        return expr

    def parse_ternary(self):
        cond = self.parse_or()
        if self.current().type == "OP" and self.current().value == "?":
            self.advance()
            then_e = self.parse_expression()
            if not (self.current().type == "OP" and self.current().value == ":"):
                raise ParseError("Expected ':' in ternary", self.current().line)
            self.advance()
            else_e = self.parse_ternary()
            return Ternary(cond=cond, then_expr=then_e, else_expr=else_e, line=cond.line)
        return cond

    def parse_or(self):
        left = self.parse_and()
        while self.current().type == "KEYWORD" and self.current().value == "or" or (self.current().type == "OP" and self.current().value == "||"):
            self.advance()
            right = self.parse_and()
            left = BinaryOp(op="or", left=left, right=right, line=left.line)
        return left

    def parse_and(self):
        left = self.parse_equality()
        while self.current().type == "KEYWORD" and self.current().value == "and" or (self.current().type == "OP" and self.current().value == "&&"):
            self.advance()
            right = self.parse_equality()
            left = BinaryOp(op="and", left=left, right=right, line=left.line)
        return left

    def parse_equality(self):
        left = self.parse_comparison()
        while self.current().type == "OP" and self.current().value in ("==", "!=", "===", "!=="):
            op = self.advance().value
            right = self.parse_comparison()
            left = BinaryOp(op=op, left=left, right=right, line=left.line)
        return left

    def parse_comparison(self):
        left = self.parse_additive()
        while self.current().type == "OP" and self.current().value in ("<", ">", "<=", ">="):
            op = self.advance().value
            right = self.parse_additive()
            left = BinaryOp(op=op, left=left, right=right, line=left.line)
        # 'is' / 'in' keywords
        while self.current().type == "KEYWORD" and self.current().value in ("is", "in"):
            op = self.advance().value
            right = self.parse_additive()
            left = BinaryOp(op=op, left=left, right=right, line=left.line)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.current().type == "OP" and self.current().value in ("+", "-"):
            # stop if newline? tokens NEWLINE handled: if current is NEWLINE, loop ends
            op = self.advance().value
            right = self.parse_multiplicative()
            left = BinaryOp(op=op, left=left, right=right, line=left.line)
        return left

    def parse_multiplicative(self):
        left = self.parse_power()
        while self.current().type == "OP" and self.current().value in ("*", "/", "%"):
            op = self.advance().value
            right = self.parse_power()
            left = BinaryOp(op=op, left=left, right=right, line=left.line)
        return left

    def parse_power(self):
        base = self.parse_unary()
        if self.current().type == "OP" and self.current().value == "**":
            self.advance()
            exp = self.parse_power()  # right assoc
            return BinaryOp(op="**", left=base, right=exp, line=base.line)
        return base

    def parse_unary(self):
        if self.current().type == "OP" and self.current().value in ("-", "+", "!", "~"):
            op = self.advance().value
            operand = self.parse_unary()
            return UnaryOp(op=op, operand=operand, line=operand.line)
        if self.current().type == "KEYWORD" and self.current().value == "not":
            self.advance()
            operand = self.parse_unary()
            return UnaryOp(op="not", operand=operand, line=operand.line)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_primary()
        while True:
            if self.current().type == "LBRACKET":
                last_token = self.tokens[self.pos - 1]
                if self.current().line != last_token.line:
                    break
            if self.current().type == "LPAREN":
                self.advance()
                args, kwargs = self.parse_call_args()
                self.expect("RPAREN", ")")
                expr = Call(callee=expr, args=args, kwargs=kwargs, line=expr.line)
            elif self.current().type == "LBRACKET":
                self.advance()
                self.skip_newlines()
                if self.current().type == "OP" and self.current().value == ":":
                    # slice [:stop] or [:]
                    start = None
                    self.advance()
                    self.skip_newlines()
                    stop = None
                    if not (self.current().type == "OP" and self.current().value == ":") and self.current().type != "RBRACKET":
                        stop = self.parse_expression()
                        self.skip_newlines()
                    step = None
                    if self.current().type == "OP" and self.current().value == ":":
                        self.advance()
                        self.skip_newlines()
                        if self.current().type != "RBRACKET":
                            step = self.parse_expression()
                            self.skip_newlines()
                    self.expect("RBRACKET", "]")
                    expr = Slice(obj=expr, start=start, stop=stop, step=step, line=expr.line)
                else:
                    idx = self.parse_expression()
                    self.skip_newlines()
                    if self.current().type == "OP" and self.current().value == ":":
                        # slice [start:stop[:step]]
                        start = idx
                        self.advance()
                        self.skip_newlines()
                        stop = None
                        if not (self.current().type == "OP" and self.current().value == ":") and self.current().type != "RBRACKET":
                            stop = self.parse_expression()
                            self.skip_newlines()
                        step = None
                        if self.current().type == "OP" and self.current().value == ":":
                            self.advance()
                            self.skip_newlines()
                            if self.current().type != "RBRACKET":
                                step = self.parse_expression()
                                self.skip_newlines()
                        self.expect("RBRACKET", "]")
                        expr = Slice(obj=expr, start=start, stop=stop, step=step, line=expr.line)
                    else:
                        self.expect("RBRACKET", "]")
                        expr = Index(obj=expr, index=idx, line=expr.line)
            elif self.current().type == "OP" and self.current().value == ".":
                self.advance()
                if self.current().type not in ("IDENT",):
                    raise ParseError("Expected member name", self.current().line)
                name = self.advance().value
                expr = Member(obj=expr, name=name, line=expr.line)
            else:
                break
        return expr

    def parse_call_args(self):
        args = []
        kwargs = []
        self.skip_newlines()
        while self.current().type != "RPAREN":
            self.skip_newlines()
            if self.current().type == "RPAREN":
                break
            # keyword arg: ident =
            if self.current().type == "IDENT" and self.peek(1).type == "OP" and self.peek(1).value == "=":
                name = self.advance().value
                self.advance()  # =
                val = self.parse_expression()
                kwargs.append((name, val))
            else:
                args.append(self.parse_expression())
            self.skip_newlines()
            if self.current().type == "OP" and self.current().value == ",":
                self.advance()
                self.skip_newlines()
                continue
            if self.current().type == "RPAREN":
                break
            raise ParseError("Expected ',' or ')'", self.current().line)
        return args, kwargs

    def parse_primary(self):
        tok = self.current()
        if tok.type == "NUMBER":
            self.advance()
            return Literal(value=tok.value, line=tok.line, col=tok.col)
        if tok.type == "STRING":
            self.advance()
            return Literal(value=tok.value, line=tok.line, col=tok.col)
        if tok.type == "FSTRING":
            self.advance()
            parts = []
            for kind, data in tok.value:
                if kind == "text":
                    parts.append(("text", data))
                else:
                    # data is token list; parse as expression
                    sub = Parser(data)
                    sub.allow_lambda = self.allow_lambda
                    expr = sub.parse_expression()
                    parts.append(("expr", expr))
            return InterpolatedString(parts=parts, line=tok.line)
        if tok.type == "KEYWORD" and tok.value in ("true", "false"):
            self.advance()
            return Literal(value=(tok.value == "true"), line=tok.line, col=tok.col)
        if tok.type == "KEYWORD" and tok.value == "nil":
            self.advance()
            return Literal(value=None, line=tok.line)
        if tok.type == "IDENT":
            # lambda: x => expr
            if self.allow_lambda and self.peek(1).type == "OP" and self.peek(1).value == "=>":
                self.advance()
                self.advance()  # =>
                body = self.parse_expression()
                return Lambda(params=[(tok.value, None, False, None, 0, 0)], body=body, line=tok.line)
            self.advance()
            return Identifier(name=tok.value, line=tok.line, col=tok.col)
        if tok.type == "KEYWORD" and tok.value == "this":
            self.advance()
            return Identifier(name="this", line=tok.line)
        if tok.type == "KEYWORD" and tok.value == "new":
            self.advance()
            if self.current().type != "IDENT":
                raise ParseError("Expected class name after new", tok.line)
            cname_col = self.current().col
            cname = self.advance().value
            args = []
            if self.match("LPAREN", "("):
                args, _ = self.parse_call_args()
                self.expect("RPAREN", ")")
            return NewExpr(class_name=cname, args=args, line=tok.line, class_name_col=cname_col)
        if tok.type == "KEYWORD" and tok.value == "fn":
            # function expression
            self.advance()
            params = self.parse_params()
            self.skip_newlines()
            body = self.parse_block()
            return FunctionExpr(params=params, body=body, line=tok.line)
        if tok.type == "LPAREN":
            self.advance()
            self.skip_newlines()
            # lambda? (params) => expr
            # detect: if next is ident and ... then => 
            # Try parse expression; if we see => handle
            # We'll check for arrow
            if self.current().type == "IDENT" or self.current().type == "RPAREN":
                # possible lambda params
                # save pos
                saved = self.pos
                try:
                    params = []
                    if self.current().type != "RPAREN":
                        # parse param list manually
                        while True:
                            if self.current().type != "IDENT":
                                raise Exception("not lambda")
                            pname = self.advance().value
                            default = None
                            if self.match("OP", "="):
                                default = self.parse_expression()
                            params.append((pname, default, False, None, 0, 0))
                            if self.current().type == "OP" and self.current().value == ",":
                                self.advance()
                                continue
                            break
                    if not (self.current().type == "RPAREN"):
                        raise Exception("not lambda")
                    self.advance()  # )
                    if not (self.current().type == "OP" and self.current().value == "=>"):
                        raise Exception("not lambda")
                    self.advance()  # =>
                    body = self.parse_expression()
                    return Lambda(params=params, body=body, line=tok.line)
                except Exception:
                    self.pos = saved
            # normal parenthesized expression
            self.skip_newlines()
            expr = self.parse_expression()
            self.skip_newlines()
            self.expect("RPAREN", ")")
            return expr
        if tok.type == "LBRACKET":
            self.advance()
            self.skip_newlines()
            if self.current().type == "RBRACKET":
                self.expect("RBRACKET", "]")
                return ListLiteral(elements=[], line=tok.line, col=tok.col)
            # spread as first element
            if self.current().type == "OP" and self.current().value == "...":
                self.advance()
                first = Spread(value=self.parse_expression(), line=tok.line)
            else:
                first = self.parse_expression()
            self.skip_newlines()
            if self.current().type == "KEYWORD" and self.current().value == "for":
                self.advance()
                if self.current().type != "IDENT":
                    raise ParseError("Expected variable in comprehension", self.current().line)
                var = self.advance().value
                if not (self.current().type == "KEYWORD" and self.current().value == "in"):
                    raise ParseError("Expected 'in' in comprehension", self.current().line)
                self.advance()
                iterable = self.parse_expression()
                self.skip_newlines()
                cond = None
                if self.current().type == "KEYWORD" and self.current().value == "if":
                    self.advance()
                    cond = self.parse_expression()
                    self.skip_newlines()
                self.expect("RBRACKET", "]")
                return ListComp(expr=first, var=var, iterable=iterable, cond=cond, line=tok.line)
            # normal list
            elems = [first]
            while self.current().type == "OP" and self.current().value == ",":
                self.advance()
                self.skip_newlines()
                if self.current().type == "RBRACKET":
                    break
                if self.current().type == "OP" and self.current().value == "...":
                    self.advance()
                    elems.append(Spread(value=self.parse_expression(), line=tok.line))
                else:
                    elems.append(self.parse_expression())
                self.skip_newlines()
            self.expect("RBRACKET", "]")
            return ListLiteral(elements=elems, line=tok.line, col=tok.col)
        if tok.type == "LBRACE":
            saved = self.pos
            self.advance()
            self.skip_newlines()
            is_dict = False
            if self.current().type == "RBRACE":
                is_dict = True  # empty dict
            else:
                try:
                    self.parse_expression()
                    if self.current().type == "OP" and self.current().value == ":":
                        is_dict = True
                except Exception:
                    is_dict = False
            self.pos = saved
            if is_dict:
                self.advance()
                self.skip_newlines()
                # empty dict
                if self.current().type == "RBRACE":
                    self.expect("RBRACE", "}")
                    return DictLiteral(pairs=[], line=tok.line, col=tok.col)
                # check comprehension: {key: val for var in iterable if cond}
                # parse first pair first
                self.skip_newlines()
                key = self.parse_expression()
                self.skip_newlines()
                self.expect("OP", ":")
                self.skip_newlines()
                val = self.parse_expression()
                self.skip_newlines()
                if self.current().type == "KEYWORD" and self.current().value == "for":
                    self.advance()
                    if self.current().type != "IDENT":
                        raise ParseError("Expected variable", self.current().line)
                    var = self.advance().value
                    if not (self.current().type == "KEYWORD" and self.current().value == "in"):
                        raise ParseError("Expected 'in'", self.current().line)
                    self.advance()
                    iterable = self.parse_expression()
                    self.skip_newlines()
                    cond = None
                    if self.current().type == "KEYWORD" and self.current().value == "if":
                        self.advance()
                        cond = self.parse_expression()
                        self.skip_newlines()
                    self.expect("RBRACE", "}")
                    return DictComp(key=key, val=val, var=var, iterable=iterable, cond=cond, line=tok.line)
                # normal dict
                pairs = [(key, val)]
                while self.current().type == "OP" and self.current().value == ",":
                    self.advance()
                    self.skip_newlines()
                    if self.current().type == "RBRACE":
                        break
                    key = self.parse_expression()
                    self.skip_newlines()
                    self.expect("OP", ":")
                    self.skip_newlines()
                    val = self.parse_expression()
                    pairs.append((key, val))
                    self.skip_newlines()
                self.expect("RBRACE", "}")
                return DictLiteral(pairs=pairs, line=tok.line, col=tok.col)
            raise ParseError("Unexpected '{'", tok.line)
        if tok.type == "OP" and tok.value == "[":
            pass
        raise ParseError("Unexpected token %r" % (tok.value,), tok.line, tok.col)

def parse(source):
    tokens = tokenize(source)
    p = Parser(tokens)
    return p.parse()
