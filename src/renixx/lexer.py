"""Lexer for the Renixx language."""
from .errors import LexError

KEYWORDS = {
    "let", "const", "fn", "return", "if", "else", "while", "for", "in",
    "break", "continue", "match", "case", "default", "class", "new", "this",
    "import", "from", "as", "export", "try", "catch", "finally", "throw",
    "true", "false", "nil", "and", "or", "not", "extends", "is",
}

TWO_CHAR = {
    "==", "!=", "<=", ">=", "&&", "||", "**", "+=", "-=", "*=", "/=",
    "%=", "->", "=>", "..",
}
THREE_CHAR = {"...", "==="}


class Token:
    __slots__ = ("type", "value", "line", "col")
    def __init__(self, type_, value, line, col):
        self.type = type_
        self.value = value
        self.line = line
        self.col = col
    def __repr__(self):
        return "Token(%s, %r, %d)" % (self.type, self.value, self.line)


class Lexer:
    def __init__(self, source):
        self.source = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.tokens = []
        self.bracket_depth = 0

    def error(self, msg):
        raise LexError(msg, self.line, self.col)

    def peek(self, n=1):
        return self.source[self.pos:self.pos + n]

    def advance(self):
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def skip_whitespace_and_comments(self):
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch in " \t\r":
                self.advance()
                continue
            if ch == "#":
                while self.pos < len(self.source) and self.source[self.pos] != "\n":
                    self.advance()
                continue
            if ch == "/" and self.peek(2) == "//":
                while self.pos < len(self.source) and self.source[self.pos] != "\n":
                    self.advance()
                continue
            if ch == "/" and self.peek(2) == "/*":
                self.advance()
                self.advance()
                while self.pos < len(self.source):
                    if self.source[self.pos] == "*" and self.peek(2) == "*/":
                        self.advance()
                        self.advance()
                        break
                    self.advance()
                else:
                    self.error("Unterminated block comment")
                continue
            break

    def read_string(self, quote):
        start_col = self.col
        triple = self.source.startswith(quote + quote + quote, self.pos)
        if triple:
            self.advance()
            self.advance()
            self.advance()
            start_line = self.line
            buf = []
            while self.pos < len(self.source):
                if self.source.startswith(quote + quote + quote, self.pos):
                    self.advance()
                    self.advance()
                    self.advance()
                    return Token("STRING", "".join(buf), start_line, start_col)
                ch = self.source[self.pos]
                if ch == "\\":
                    self.advance()
                    esc = self.advance()
                    mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                               '"': '"', "'": "'", "0": "\0"}
                    buf.append(mapping.get(esc, esc))
                else:
                    if ch == "\n":
                        self.line += 1
                        self.col = 1
                    else:
                        self.col += 1
                    buf.append(ch)
                    self.pos += 1
            self.error("Unterminated string")
        # single-quoted or double-quoted
        self.advance()  # opening quote
        start_line = self.line
        # double quotes support interpolation {expr}
        if quote == '"' :
            parts = []
            buf = []
            while self.pos < len(self.source) and self.source[self.pos] != quote and self.source[self.pos] != "\n":
                ch = self.source[self.pos]
                if ch == "\\":
                    self.advance()
                    esc = self.advance()
                    mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                               '"': '"', "'": "'", "0": "\0"}
                    buf.append(mapping.get(esc, esc))
                    continue
                if ch == "{":
                    if buf:
                        parts.append(("text", "".join(buf)))
                        buf = []
                    # find matching }
                    depth = 1
                    i = self.pos + 1
                    in_str = None
                    while i < len(self.source) and depth > 0:
                        c = self.source[i]
                        if in_str:
                            if c == "\\":
                                i += 2
                                continue
                            if c == in_str:
                                in_str = None
                            i += 1
                            continue
                        if c in ('"', "'"):
                            in_str = c
                            i += 1
                            continue
                        if c == "{":
                            depth += 1
                        elif c == "}":
                            depth -= 1
                            if depth == 0:
                                break
                        i += 1
                    if depth != 0:
                        self.error("Unterminated interpolation")
                    inner_src = self.source[self.pos+1:i]
                    base_line = self.line
                    base_col = self.col
                    # advance pos past the braces
                    # update line/col by consuming
                    for cc in self.source[self.pos:i+1]:
                        if cc == "\n":
                            self.line += 1
                            self.col = 1
                        else:
                            self.col += 1
                    self.pos = i + 1
                    inner_tokens = tokenize(inner_src)
                    while inner_tokens and inner_tokens[-1].type in ("NEWLINE", "EOF"):
                        inner_tokens.pop()
                    # offset inner token positions to original source
                    for tok in inner_tokens:
                        tok.line += base_line - 1
                        if tok.line == base_line:
                            tok.col += base_col
                    parts.append(("expr", inner_tokens))
                    continue
                buf.append(ch)
                self.advance()
            if self.pos >= len(self.source) or self.source[self.pos] != quote:
                self.error("Unterminated string")
            self.advance()  # closing quote
            if buf:
                parts.append(("text", "".join(buf)))
            if any(p[0] == "expr" for p in parts):
                return Token("FSTRING", parts, start_line, start_col)
            # collapse to plain string
            text = "".join(p[1] for p in parts)
            return Token("STRING", text, start_line, start_col)
        # single-quoted: plain
        buf = []
        while self.pos < len(self.source) and self.source[self.pos] != quote and self.source[self.pos] != "\n":
            ch = self.source[self.pos]
            if ch == "\\":
                self.advance()
                esc = self.advance()
                mapping = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\",
                           '"': '"', "'": "'", "0": "\0"}
                buf.append(mapping.get(esc, esc))
            else:
                buf.append(ch)
                self.advance()
        if self.pos >= len(self.source) or self.source[self.pos] != quote:
            self.error("Unterminated string")
        self.advance()  # closing quote
        return Token("STRING", "".join(buf), start_line, start_col)


    def read_number(self):
        start_col = self.col
        start = self.pos
        start_line = self.line
        if self.source[self.pos] == "0" and self.pos + 1 < len(self.source) and self.source[self.pos + 1].lower() == "x":
            self.advance()
            self.advance()
            while self.pos < len(self.source) and (self.source[self.pos].isalnum() or self.source[self.pos] == "_"):
                self.advance()
            raw = self.source[start:self.pos].replace("_", "")
            try:
                val = int(raw, 16)
            except ValueError:
                self.error("Invalid hex number")
            return Token("NUMBER", val, start_line, start_col)
        if self.source[self.pos] == "0" and self.pos + 1 < len(self.source) and self.source[self.pos + 1].lower() == "b":
            self.advance()
            self.advance()
            while self.pos < len(self.source) and self.source[self.pos] in "01_":
                self.advance()
            raw = self.source[start:self.pos].replace("_", "")
            try:
                val = int(raw, 2)
            except ValueError:
                self.error("Invalid binary number")
            return Token("NUMBER", val, start_line, start_col)
        has_dot = False
        has_exp = False
        while self.pos < len(self.source):
            ch = self.source[self.pos]
            if ch.isdigit() or ch == "_":
                self.advance()
            elif ch == "." and not has_dot and self.pos + 1 < len(self.source) and self.source[self.pos + 1].isdigit():
                has_dot = True
                self.advance()
            elif ch in "eE" and not has_exp:
                has_exp = True
                self.advance()
                if self.pos < len(self.source) and self.source[self.pos] in "+-":
                    self.advance()
            else:
                break
        raw = self.source[start:self.pos].replace("_", "")
        try:
            if has_dot or has_exp or "e" in raw.lower():
                val = float(raw)
            else:
                val = int(raw)
        except ValueError:
            self.error("Invalid number")
        return Token("NUMBER", val, start_line, start_col)

    def read_ident(self):
        start_col = self.col
        start = self.pos
        start_line = self.line
        while self.pos < len(self.source) and (self.source[self.pos].isalnum() or self.source[self.pos] == "_"):
            self.advance()
        word = self.source[start:self.pos]
        if word in KEYWORDS:
            return Token("KEYWORD", word, start_line, start_col)
        return Token("IDENT", word, start_line, start_col)

    def tokenize(self):
        while True:
            self.skip_whitespace_and_comments()
            col = self.col
            if self.pos >= len(self.source):
                if self.tokens and self.tokens[-1].type != "NEWLINE":
                    self.tokens.append(Token("NEWLINE", "\n", self.line, col))
                self.tokens.append(Token("EOF", None, self.line, col))
                break

            ch = self.source[self.pos]
            line = self.line
            col = self.col

            # backslash line continuation
            if ch == "\\" and self.pos + 1 < len(self.source) and self.source[self.pos + 1] == "\n":
                self.advance()
                self.advance()
                continue

            # newline handling
            if ch == "\n":
                self.advance()
                if self.bracket_depth == 0:
                    if not self.tokens or self.tokens[-1].type != "NEWLINE":
                        self.tokens.append(Token("NEWLINE", "\n", line, col))
                continue

            # strings
            if ch in ('"', "'"):
                tok = self.read_string(ch)
                self.tokens.append(tok)
                continue

            # numbers
            if ch.isdigit():
                tok = self.read_number()
                self.tokens.append(tok)
                continue

            # identifiers / keywords
            if ch.isalpha() or ch == "_":
                tok = self.read_ident()
                self.tokens.append(tok)
                continue

            # operators / punctuation
            three = self.source[self.pos:self.pos + 3]
            two = self.source[self.pos:self.pos + 2]
            if three in THREE_CHAR:
                self.tokens.append(Token("OP", three, line, col))
                self.advance()
                self.advance()
                self.advance()
                continue
            if two in TWO_CHAR:
                self.tokens.append(Token("OP", two, line, col))
                self.advance()
                self.advance()
                continue

            if ch in "([{":
                self.bracket_depth += 1
                t = "LPAREN" if ch == "(" else ("LBRACKET" if ch == "[" else "LBRACE")
                self.tokens.append(Token(t, ch, line, col))
                self.advance()
                continue
            if ch in ")]}":
                self.bracket_depth = max(0, self.bracket_depth - 1)
                t = "RPAREN" if ch == ")" else ("RBRACKET" if ch == "]" else "RBRACE")
                self.tokens.append(Token(t, ch, line, col))
                self.advance()
                continue

            if ch in "+-*/%<>=!&|^~?:,;.":
                self.tokens.append(Token("OP", ch, line, col))
                self.advance()
                continue

            self.error("Unexpected character %r" % ch)

        return self.tokens


def tokenize(source):
    return Lexer(source).tokenize()
