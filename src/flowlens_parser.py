#!/usr/bin/env python3
"""JSL FlowLens - parser and model builder.

Parses JSL source files (or a whole .jmpaddin archive), extracts structure
(functions, expressions, variables, includes, calls, side effects), infers a
linear best-effort execution order from the entry point, and emits a JSON
model. Optionally injects the model into an HTML template to produce a
standalone, browser-openable visualization.

Stdlib only, so it runs unchanged inside JMP's embedded Python.

License: MIT. Copyright (c) 2026 Florian.
"""

import argparse
import ast
import json
import os
import re
import sys
import tempfile
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

VERSION = "0.6.0"
MAX_STEPS = 400
MAX_EMBED_CHARS = 250000   # per-file source embedded in the HTML output

# ----------------------------------------------------------------------
# Low-level scanning helpers
# ----------------------------------------------------------------------

def strip_comments(code):
    """Replace comments with spaces (offsets preserved). Return
    (clean_code, comments) where comments is a list of (line, text)."""
    out = list(code)
    comments = []
    i, n = 0, len(code)
    line = 1
    in_str = False
    while i < n:
        c = code[i]
        if c == "\n":
            line += 1
            i += 1
            continue
        if in_str:
            if c == "\\" and i + 1 < n and code[i + 1] == "!":
                i += 3  # JSL escape sequence \!x
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            i += 1
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "/":
            j = code.find("\n", i)
            if j == -1:
                j = n
            comments.append((line, code[i + 2:j].strip()))
            for k in range(i, j):
                out[k] = " "
            i = j
            continue
        if c == "/" and i + 1 < n and code[i + 1] == "*":
            j = code.find("*/", i + 2)
            j = n if j == -1 else j + 2
            comments.append((line, code[i + 2:j - 2].strip()))
            for k in range(i, j):
                if out[k] != "\n":
                    out[k] = " "
            line += code.count("\n", i, j)
            i = j
            continue
        i += 1
    return "".join(out), comments


def line_of(code, offset):
    return code.count("\n", 0, offset) + 1


def match_paren(code, open_idx):
    """Index of the closing paren/brace/bracket matching code[open_idx]."""
    pairs = {"(": ")", "{": "}", "[": "]"}
    close = pairs[code[open_idx]]
    opener = code[open_idx]
    depth = 0
    in_str = False
    i = open_idx
    n = len(code)
    while i < n:
        c = code[i]
        if in_str:
            if c == "\\" and i + 1 < n and code[i + 1] == "!":
                i += 3
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif c == opener:
            depth += 1
        elif c == close:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def split_top_level(code, seps=";,"):
    """Split code at depth 0 by seps. Returns list of (offset, text)."""
    parts = []
    depth = 0
    in_str = False
    start = 0
    i, n = 0, len(code)
    while i < n:
        c = code[i]
        if in_str:
            if c == "\\" and i + 1 < n and code[i + 1] == "!":
                i += 3
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
        elif c in "({[":
            depth += 1
        elif c in ")}]":
            depth -= 1
        elif depth == 0 and c in seps:
            part = code[start:i]
            if part.strip():
                parts.append((start, part))
            start = i + 1
        i += 1
    part = code[start:n]
    if part.strip():
        parts.append((start, part))
    return parts


# ----------------------------------------------------------------------
# Extraction
# ----------------------------------------------------------------------

# JSL is case-insensitive and names may contain spaces
# (e.g. "Workflow for Sample Data = function({}, ...)")
DEF_RE = re.compile(
    r"(?:^|[;,(\n])\s*([A-Za-z_][A-Za-z0-9_ ]*?)\s*=\s*(Function|Expr)\s*\(",
    re.I)
INCLUDE_RE = re.compile(r"\bInclude\s*\(\s*\"([^\"]+)\"")
CONFIG_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(\"[^\"]*\"|-?\d+(?:\.\d+)?)\s*$")

# any assignment (not ==, <=, >=, !=), optionally namespace-qualified
ASSIGN_RE = re.compile(
    r"(?:^|[;,(\n])\s*(?:(::|[A-Za-z_][A-Za-z0-9_]*:))?"
    r"([A-Za-z_][A-Za-z0-9_ ]*?)\s*=(?![=<>])")
# JSL keywords that look like assignments but are arguments, not variables
NOT_VARS = {"x", "y", "size", "title", "value", "width", "height", "min col",
            "max col", "formula", "format", "set", "get"}

EFFECT_PATTERNS = [
    ("table",  re.compile(r"\bNew Table\s*\(\s*(\"([^\"]*)\")?")),
    ("table",  re.compile(r"<<\s*(Subset|Summary)\s*\(")),
    ("window", re.compile(r"\bNew Window\s*\(\s*(\"([^\"]*)\"|[A-Za-z_][A-Za-z0-9_]*)?")),
    ("column", re.compile(r"\bNew Column\s*\(\s*(\"([^\"]*)\")?")),
    ("file",   re.compile(r"\bSave Text File\s*\(")),
    ("file",   re.compile(r"\bLoad Text File\s*\(")),
    ("file",   re.compile(r"\bOpen\s*\(\s*\"([^\"]+)\"")),
    ("file",   re.compile(r"\bPick (?:File|Directory)\s*\(\s*(\"([^\"]*)\")?")),
    ("tableop", re.compile(
        r"\bData Table\s*\(\s*\"[^\"]*\"\s*\)\s*(?::[^<;\n]{0,90})?<<\s*"
        r"([A-Za-z][A-Za-z0-9 ]*)")),
    ("tableop", re.compile(r"\bClose\s*\(\s*Data Table\s*\(\s*\"([^\"]*)\"()")),
    ("log",    re.compile(r"\bShow\s*\(\s*(\"([^\"]*)\")?")),
    ("error",  re.compile(r"\bThrow\s*\(\s*(\"([^\"]*)\")?")),
]

# report-producing platform messages (rendered as reports, not raw table ops)
PLATFORMS = {"graph builder", "explore outliers", "distribution", "fit model",
             "bivariate", "oneway", "tabulate", "text explorer", "fit group",
             "multivariate", "fit least squares", "profiler", "control chart",
             "process capability", "partition", "neural"}

WFSTEP_RE = re.compile(r"\s*step_?name\s*=\s*\"([^\"]*)\"", re.I | re.S)

# any object receiving a platform message, e.g. dt << Graph Builder(...)
EFFECT_PATTERNS.append(("report", re.compile(
    r"<<\s*(" + "|".join(re.escape(p) for p in
                         sorted(PLATFORMS, key=len, reverse=True)) + r")\s*\(",
    re.I)))
EFFECT_PATTERNS.append(("window", re.compile(
    r"\b(Column Dialog|Modal Dialog)\s*\(", re.I)))

CONTAINER_RE = re.compile(r"^\s*(If|For|While|Try)\s*\(")

# JSL <-> Python bridge
PYSUBMIT_RE = re.compile(r"\bPython\s+Submit\s*\(", re.I)
PYSEND_RE = re.compile(r"\bPython\s+Send\s*\(\s*([^),]*)", re.I)
PYGET_RE = re.compile(r"\bPython\s+Get\s*\(\s*([^),]*)", re.I)
PYEXEC_RE = re.compile(r"\bPython\s+Execute\s*\(", re.I)


# ----------------------------------------------------------------------
# Languages and string literals
# ----------------------------------------------------------------------

def detect_lang(name, code=""):
    """jsl | python | notebook, from the file extension or the content."""
    n = (name or "").lower()
    if n.endswith(".py"):
        return "python"
    if n.endswith(".jmpnb"):
        return "notebook"
    if n.endswith(".jsl"):
        return "jsl"
    head = (code or "")[:4000]
    if re.search(r"^\s*﻿?Notebook\s*\(", head):
        return "notebook"
    jsl_hits = len(re.findall(
        r"Names Default To Here|<<\s*[A-Z]|New Table\s*\(|Data Table\s*\(|"
        r"\bFunction\s*\(\s*\{|Show\s*\(", head, re.I))
    py_hits = len(re.findall(
        r"^\s*(?:import|from)\s+\w|^\s*def\s+\w+\s*\(|^\s*class\s+\w+|"
        r"^\s*print\s*\(", head, re.M))
    return "python" if py_hits > jsl_hits else "jsl"


def unescape_jsl(s):
    """Resolve the JSL escape sequences used inside quoted strings."""
    if "\\!" not in s:
        return s
    out = []
    i, n = 0, len(s)
    mapping = {'"': '"', "n": "\n", "r": "\r", "t": "\t", "\\": "\\",
               "b": "\b", "f": "\f", "0": "\0"}
    while i < n:
        if s[i] == "\\" and i + 2 < n and s[i + 1] == "!":
            out.append(mapping.get(s[i + 2], s[i + 2]))
            i += 3
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def read_jsl_string(code, start):
    """Read the JSL string literal at/after `start`.

    Handles both the quoted form and the raw form "\\[ ... ]\\".
    Returns (value, content_offset) or (None, -1). content_offset is the
    offset of the first character of the value inside `code`, so callers can
    turn inner line numbers into real file line numbers.
    """
    i, n = start, len(code)
    while i < n and code[i] in " \t\r\n":
        i += 1
    if i >= n or code[i] != '"':
        return None, -1
    # raw string:  "\[ ... ]\"
    if code.startswith('"\\[', i):
        c0 = i + 3
        end = code.find(']\\"', c0)
        if end == -1:
            return None, -1
        return code[c0:end], c0
    # ordinary quoted string with \!x escapes
    c0 = i + 1
    j = c0
    while j < n:
        if code[j] == "\\" and j + 2 < n and code[j + 1] == "!":
            j += 3
            continue
        if code[j] == '"':
            return unescape_jsl(code[c0:j]), c0
        j += 1
    return None, -1


class JslFile:
    def __init__(self, name, raw):
        self.name = name
        self.raw = raw
        self.clean, self.comments = strip_comments(raw)
        self.header = self._header_comment()
        self.includes = INCLUDE_RE.findall(self.clean)
        self.defs = {}       # name -> def dict
        self.variables = []
        self.top_span = None  # clean code with def bodies blanked

    def _header_comment(self):
        lines = []
        for ln, txt in self.comments:
            if ln <= len(lines) + 3 and txt:
                lines.append(txt)
            if ln > 5:
                break
        return " ".join(lines[:4])

    def doc_for_line(self, line):
        """Comment text on the lines directly above `line` (first sentence)."""
        best = []
        for ln, txt in self.comments:
            if 0 < line - ln <= 2 and txt:
                best.append(txt)
        doc = " ".join(best)
        for stop in (". ", "; "):
            if stop in doc:
                doc = doc.split(stop)[0] + "."
                break
        return doc[:140]


def extract_defs(f):
    """Find Function/Expr definitions and blank their bodies out of a copy
    of the clean code so top-level statement walking skips them."""
    blanked = list(f.clean)
    for m in DEF_RE.finditer(f.clean):
        name, kind = m.group(1).strip(), m.group(2).capitalize()
        open_idx = f.clean.find("(", m.end() - 1)
        close_idx = match_paren(f.clean, open_idx)
        if close_idx == -1:
            continue
        body = f.clean[open_idx + 1:close_idx]
        args = []
        am = re.search(r"\{([^}]*)\}", body)
        if kind == "Function" and am:
            args = [a.strip() for a in am.group(1).split(",") if a.strip()]
            # walk body after the locals list if present
            rest = body[am.end():]
            lm = re.match(r"\s*,\s*\{[^}]*\}", rest)
            walk_body = rest[lm.end():] if lm else rest
            body_off = open_idx + 1 + am.end() + (lm.end() if lm else 0)
        else:
            walk_body = body
            body_off = open_idx + 1
        line = line_of(f.clean, m.start(1))
        f.defs[name] = {
            "id": f"{f.name}::{name}",
            "name": name,
            "kind": kind,
            "file": f.name,
            "args": args,
            "line": line,
            "doc": f.doc_for_line(line),
            "body": walk_body,
            "body_off": body_off,
            "src": f.raw[m.start(1):close_idx + 1][:6000],
            "endline": line_of(f.clean, close_idx),
        }
        for k in range(m.start(1), close_idx + 1):
            if blanked[k] != "\n":
                blanked[k] = " "
    f.top_span = "".join(blanked)


def extract_variables(f):
    for off, stmt in split_top_level(f.top_span, ";"):
        m = CONFIG_RE.match(stmt.strip())
        if m:
            # line of the first real character, not of the separator before it
            lead = len(stmt) - len(stmt.lstrip())
            f.variables.append({
                "name": m.group(1),
                "value": m.group(2).strip('"'),
                "file": f.name,
                "line": line_of(f.top_span, off + lead),
            })


def skip_args(inner, n):
    """Drop the first n top-level comma-separated arguments.

    If(cond, body...) / For(init, cond, incr, body...) / While(cond, body...)
    all carry control machinery in their leading arguments; only what follows
    is executable body. Returns (text, offset_within_inner)."""
    if n <= 0:
        return inner, 0
    parts = split_top_level(inner, ",")
    if len(parts) <= n:
        return "", 0
    off = parts[n][0]
    return inner[off:], off


def extract_dataflow(files, all_defs):
    """Which variables exist, and which component writes or reads each one.

    Gives the graph a third kind of node (alongside functions and
    expressions) and directed read/write edges, so a viewer can follow
    producer -> variable -> consumer chains."""
    variables = {}          # name -> dict
    flows = set()           # (component_id, var_name, "read"|"write")

    def note_var(name, file, line, value="", setting=False):
        key = name
        if key not in variables:
            variables[key] = {"name": name, "file": file, "line": line,
                              "value": value, "setting": setting}
        elif setting and not variables[key]["setting"]:
            variables[key].update(value=value, setting=True,
                                  file=file, line=line)

    # top-level assignments in every JSL file
    for f in files.values():
        if not isinstance(f, JslFile):
            continue
        for off, stmt in split_top_level(f.top_span, ";"):
            m = ASSIGN_RE.search(stmt)
            if not m:
                continue
            name = m.group(2).strip()
            if not name or name.lower() in NOT_VARS or name in all_defs:
                continue
            lead = len(stmt) - len(stmt.lstrip())
            line = line_of(f.top_span, off + lead)
            lit = CONFIG_RE.match(stmt.strip())
            note_var(name, f.name, line,
                     lit.group(2).strip('"') if lit else "", bool(lit))

    # Python module-level assignments
    for f in files.values():
        if isinstance(f, PyFile):
            for v in f.variables:
                note_var(v["name"], v["file"], v["line"], v["value"], True)

    # who writes and who reads each variable
    for d in all_defs.values():
        body = d.get("body") or d.get("src") or ""
        if not body:
            continue
        for m in ASSIGN_RE.finditer(body):
            nm = m.group(2).strip()
            if nm in variables:
                flows.add((d["id"], nm, "write"))
        for name in variables:
            if re.search(r"(?<![A-Za-z0-9_])" + re.escape(name)
                         + r"(?![A-Za-z0-9_])", body):
                if (d["id"], name, "write") not in flows:
                    flows.add((d["id"], name, "read"))
    return variables, flows


def scan_events(text, base_line_code, base_off, known):
    """Find effects and calls in text, ordered by offset.
    Returns list of (offset, kind, payload)."""
    events = []
    for kind, rx in EFFECT_PATTERNS:
        for m in rx.finditer(text):
            detail = ""
            if m.groups():
                g = m.group(2) if len(m.groups()) > 1 and m.group(2) else (m.group(1) or "")
                detail = g.strip('"').strip()
            if kind == "tableop":
                low = detail.lower()
                if low == "new column":
                    continue  # covered by the column pattern
                if low in PLATFORMS:
                    kind = "report"
            if kind == "file" and "/" in detail:
                detail = detail.rstrip("/").split("/")[-1]
            events.append((m.start(), "effect", (kind, detail,
                           line_of(base_line_code, base_off + m.start()))))
    # two patterns can describe the same construct (e.g. a platform message
    # on a named data table) - keep only the first of each
    seen, uniq = set(), []
    for off, etype, payload in events:
        key = (etype,) + tuple(payload) if etype == "effect" else None
        if key is not None:
            if key in seen:
                continue
            seen.add(key)
        uniq.append((off, etype, payload))
    events = uniq
    for name in known:
        for m in re.finditer(r"\b" + re.escape(name) + r"\s*\(", text):
            events.append((m.start(), "call", (name,
                           line_of(base_line_code, base_off + m.start()))))
        # Expr invocation: Eval(name) or bare statement
        for m in re.finditer(r"\bEval\s*\(\s*" + re.escape(name) + r"\b", text):
            events.append((m.start(), "call", (name,
                           line_of(base_line_code, base_off + m.start()))))
    events.sort(key=lambda e: e[0])
    return events


# ----------------------------------------------------------------------
# Python analysis (uses the standard-library ast module)
# ----------------------------------------------------------------------

# method name -> (effect kind, description key)
PY_METHOD_EFFECTS = {
    "new_column": "column",
    "add_rows": "tableop",
    "delete_columns": "tableop",
    "delete_rows": "tableop",
    "save": "file",
    "to_csv": "file",
    "to_excel": "file",
    "to_parquet": "file",
    "to_json": "file",
    "savefig": "plot",
    "show": "plot",
    "fit": "model",
    "fit_predict": "model",
    "fit_transform": "model",
    "predict": "model",
    "run_jsl": "jsl",
    "submit": "jsl",
}
PY_FUNC_EFFECTS = {
    "print": "log",
    "open": "file",
    "read_csv": "file",
    "read_parquet": "file",
    "read_excel": "file",
    "read_json": "file",
    "read_table": "file",
    "jpip": "pkg",
}
PY_PLOT_MODULES = {"plt", "pyplot", "matplotlib", "sns", "seaborn", "px"}


def py_name(node):
    """Dotted name for Name/Attribute nodes: jmp.DataType.Numeric -> that."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif isinstance(node, ast.Call):
        parts.append("()")
    return ".".join(reversed(parts))


def py_str_arg(node, idx=0):
    """First string argument of a call, if it is a literal."""
    try:
        a = node.args[idx]
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            return a.value
    except IndexError:
        pass
    return ""


def py_leading_comment(lines, lineno):
    """Comment block directly above a definition (1-based lineno)."""
    out = []
    i = lineno - 2
    while i >= 0 and lines[i].strip().startswith("#"):
        out.append(lines[i].strip().lstrip("#").strip())
        i -= 1
        if len(out) >= 3:
            break
    return " ".join(reversed(out))[:140]


class PyFile:
    """A Python source unit: a .py file, an embedded Python block, or a
    notebook cell. `line_offset` maps inner lines onto the real file."""

    lang = "python"

    def __init__(self, name, raw, line_offset=0, host=None):
        self.name = name
        self.raw = raw
        self.line_offset = line_offset
        self.host = host or name
        self.lines = raw.split("\n")
        self.tree = None
        self.error = ""
        try:
            self.tree = ast.parse(raw)
        except SyntaxError as e:
            self.error = "line %s: %s" % (e.lineno, e.msg)
        except Exception as e:                      # very defensive
            self.error = str(e)
        self.defs = {}
        self.variables = []
        self.includes = []
        self.header = self._header()
        self.estimators = {}      # variable -> class it was constructed from
        if self.tree is not None:
            self._extract_defs()
            self._extract_variables()
            self._extract_estimators()

    def line(self, node):
        return getattr(node, "lineno", 1) + self.line_offset

    def endline(self, node):
        return (getattr(node, "end_lineno", None) or
                getattr(node, "lineno", 1)) + self.line_offset

    def src(self, node, limit=4000):
        a = getattr(node, "lineno", 1) - 1
        b = getattr(node, "end_lineno", None) or getattr(node, "lineno", 1)
        return "\n".join(self.lines[a:b])[:limit]

    def _header(self):
        out = []
        for ln in self.lines[:6]:
            t = ln.strip()
            if t.startswith("#"):
                out.append(t.lstrip("#").strip())
            elif t and not t.startswith('"""'):
                break
        return " ".join(out)[:200]

    def _extract_defs(self):
        for node in self.tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                is_cls = isinstance(node, ast.ClassDef)
                args = []
                if not is_cls:
                    args = [a.arg for a in node.args.args]
                doc = ast.get_docstring(node) or py_leading_comment(
                    self.lines, node.lineno)
                self.defs[node.name] = {
                    "id": "%s::%s" % (self.name, node.name),
                    "name": node.name,
                    "kind": "class" if is_cls else "def",
                    "lang": "python",
                    "file": self.host,
                    "args": args,
                    "line": self.line(node),
                    "endline": self.endline(node),
                    "doc": (doc or "").split("\n")[0][:140],
                    "src": self.src(node, 6000),
                    "node": node,
                }

    def _extract_variables(self):
        """Top-level assignments of literal values = things a user can tune."""
        for node in self.tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) \
                    and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, (str, int, float)):
                self.variables.append({
                    "name": node.targets[0].id,
                    "value": str(node.value.value)[:120],
                    "file": self.host,
                    "line": self.line(node),
                })


def py_model_label(pf, call):
    """Name the thing being fitted: LinearRegression().fit -> that class;
    clf.fit -> whatever clf was constructed from."""
    obj = getattr(call.func, "value", None)
    if isinstance(obj, ast.Call):
        return py_name(obj.func).split(".")[-1]
    name = py_name(obj) if obj is not None else ""
    short = name.split(".")[-1]
    return pf.estimators.get(short, short) or short


def py_src_of(pf, node):
    """Readable source for an expression node."""
    try:
        return ast.unparse(node)
    except Exception:
        return pf.src(node, 120)


def _py_extract_estimators(self):
    """clf = IsolationForest(...) -> {'clf': 'IsolationForest'}"""
    for node in ast.walk(self.tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            val = node.value
            if isinstance(val, ast.Call):
                cls = py_name(val.func).split(".")[-1]
                # unwrap chained construction: Model(...).fit(...)
                inner = getattr(val.func, "value", None)
                if not cls[:1].isupper() and isinstance(inner, ast.Call):
                    cls = py_name(inner.func).split(".")[-1]
                if cls[:1].isupper():
                    self.estimators[node.targets[0].id] = cls


PyFile._extract_estimators = _py_extract_estimators


def py_scan_calls(node):
    """All Call nodes inside a statement, in source order."""
    calls = [n for n in ast.walk(node) if isinstance(n, ast.Call)]
    calls.sort(key=lambda c: (getattr(c, "lineno", 0),
                              getattr(c, "col_offset", 0)))
    return calls


# ----------------------------------------------------------------------
# Notebook (.jmpnb) analysis
# ----------------------------------------------------------------------

BLOCK_RE = re.compile(r"\bBlock\s*\(")
NB_TYPE_RE = re.compile(r"\bType\s*\(\s*\"(\w+)\"\s*\)")
NB_TITLE_RE = re.compile(r"\bTitle\s*\(\s*\"")
NB_NAME_RE = re.compile(r"\"Name\"n\s*\(\s*\"|\bName\s*\(\s*\"")
NB_CONTENT_RE = re.compile(r"\bContent\s*\(\s*")
NB_HIDDEN_RE = re.compile(r"\bHidden\s*\(\s*1\s*\)")


class NotebookFile:
    """A JMP Notebook: Notebook(Children(Block(...), ...)).

    The container is JSL-expression syntax; each Block carries a Type
    (Text / Section / Python / JSL) and its code in Content("...")."""

    lang = "notebook"

    def __init__(self, name, raw):
        self.name = name
        self.raw = raw
        self.clean, self.comments = strip_comments(raw)
        self.defs = {}
        self.variables = []
        self.includes = []
        self.cells = []
        self.title = ""
        m = NB_TITLE_RE.search(self.clean)
        if m:
            val, _ = read_jsl_string(self.clean, m.end() - 1)
            self.title = (val or "").strip()
        self.header = self.title
        self._extract_cells()

    def _extract_cells(self):
        """Every Block in document order, with its own span only (so a
        Section does not swallow the blocks nested inside it)."""
        code = self.clean
        spans = []
        for m in BLOCK_RE.finditer(code):
            op = code.find("(", m.end() - 1)
            cl = match_paren(code, op)
            if cl == -1:
                continue
            spans.append((m.start(), op + 1, cl))
        for start, inner_start, cl in spans:
            body = code[inner_start:cl]
            # ignore anything belonging to a nested Block
            nested = BLOCK_RE.search(body)
            own = body[:nested.start()] if nested else body
            tm = NB_TYPE_RE.search(own)
            if not tm:
                continue
            btype = tm.group(1)
            title = ""
            nm = NB_TITLE_RE.search(own) or NB_NAME_RE.search(own)
            if nm:
                val, _ = read_jsl_string(own, nm.end() - 1)
                title = (val or "").strip()
            content, cline = "", line_of(code, start)
            cm = NB_CONTENT_RE.search(own)
            if cm:
                val, coff = read_jsl_string(own, cm.end())
                if val is not None:
                    content = val
                    cline = line_of(code, inner_start + coff)
            self.cells.append({
                "type": btype,
                "lang": {"Python": "python", "JSL": "jsl"}.get(btype, "text"),
                "title": title,
                "content": content,
                "line": line_of(code, start),
                "content_line": cline,
                "hidden": bool(NB_HIDDEN_RE.search(own)),
            })


# ----------------------------------------------------------------------
# Step engine (linear best-effort walk)
# ----------------------------------------------------------------------

MAX_EXPANSIONS = 1  # max times a function body is re-expanded in the walk


class Walker:
    def __init__(self, files, all_defs):
        self.files = files
        self.defs = all_defs          # name -> def
        self.steps = []
        self.edges = set()
        self.expansions = {}          # name -> times body was expanded
        self.walked_includes = set()  # file names whose top level was walked

    def emit(self, **kw):
        if len(self.steps) >= MAX_STEPS:
            raise OverflowError("step limit")
        kw.setdefault("lang", "jsl")
        kw["i"] = len(self.steps)
        self.steps.append(kw)

    def walk_span(self, text, base_code, base_off, file, owner,
                  depth, cond, loop, stack):
        for off, stmt in split_top_level(text, ";,"):
            s = stmt.strip()
            if not s:
                continue
            # line of the first real character of this statement, so that
            # code extracts and their line numbers line up exactly
            lead = len(stmt) - len(stmt.lstrip())
            stmt_line = line_of(base_code, base_off + off + lead)
            wf = WFSTEP_RE.match(stmt)
            if wf:
                self.emit(type="wfstep", file=file, owner=owner,
                          detail=wf.group(1).strip(), line=stmt_line,
                          depth=depth, conditional=cond, loop=loop,
                          src=s[:1000], srcline=stmt_line)
                continue
            # --- JSL -> Python bridge ------------------------------
            for rx, kind in ((PYSEND_RE, "pysend"), (PYGET_RE, "pyget")):
                m = rx.search(stmt)
                if m:
                    self.emit(type=kind, file=file, owner=owner, lang="jsl",
                              detail=m.group(1).strip(), line=stmt_line,
                              depth=depth, conditional=cond, loop=loop,
                              src=s[:1000], srcline=stmt_line)
            pym = PYSUBMIT_RE.search(stmt) or PYEXEC_RE.search(stmt)
            if pym:
                code_val, coff = read_jsl_string(stmt, pym.end())
                self.emit(type="pyblock", file=file, owner=owner, lang="python",
                          detail="", line=stmt_line, depth=depth,
                          conditional=cond, loop=loop, src=s[:4000],
                          srcline=stmt_line)
                if code_val:
                    inner_line = line_of(base_code, base_off + off + coff)
                    pf = PyFile(file + " (Python)", code_val,
                                line_offset=inner_line - 1, host=file)
                    self.walk_python(pf, owner, depth + 1, cond, loop, stack)
                continue
            if PYSEND_RE.search(stmt) or PYGET_RE.search(stmt):
                continue
            cm = CONTAINER_RE.match(s)
            if cm:
                kw = cm.group(1)
                open_idx = stmt.find("(", cm.end() - 1)
                close_idx = match_paren(stmt, open_idx)
                inner = stmt[open_idx + 1:close_idx] if close_idx > 0 else ""
                line = stmt_line
                # walk only the body, not the control machinery in the
                # leading arguments (condition, initialiser, increment)
                if kw == "If":
                    cond_txt = inner.split(",")[0].strip()[:60]
                    self.emit(type="branch", file=file, owner=owner,
                              detail=cond_txt, line=line, depth=depth,
                              conditional=cond, loop=loop, src=s[:4000],
                              srcline=line)
                    body, boff = skip_args(inner, 1)
                    self.walk_span(body, base_code,
                                   base_off + off + open_idx + 1 + boff,
                                   file, owner, depth + 1, True, loop, stack)
                elif kw in ("For", "While"):
                    self.emit(type="loop", file=file, owner=owner,
                              detail=kw, line=line, depth=depth,
                              conditional=cond, loop=loop, src=s[:4000],
                              srcline=line)
                    body, boff = skip_args(inner, 3 if kw == "For" else 1)
                    self.walk_span(body, base_code,
                                   base_off + off + open_idx + 1 + boff,
                                   file, owner, depth + 1, cond, True, stack)
                else:  # Try
                    self.walk_span(inner, base_code, base_off + off + open_idx + 1,
                                   file, owner, depth, cond, loop, stack)
                continue
            inc = INCLUDE_RE.search(stmt)
            if inc:
                self.emit(type="include", file=file, owner=owner,
                          detail=inc.group(1), line=stmt_line,
                          depth=depth, conditional=cond, loop=loop,
                          src=s[:1000], srcline=stmt_line)
                # follow the include: its top-level code runs now
                target = os.path.basename(inc.group(1))
                f2 = self.files.get(target)
                if f2 is not None and target not in self.walked_includes:
                    self.walked_includes.add(target)
                    self.walk_span(f2.top_span, f2.top_span, 0, target,
                                   f"{target}::__top__", depth, cond, loop,
                                   stack)
                continue
            emitted = 0
            for ev_off, ev_type, payload in scan_events(
                    stmt, base_code, base_off + off, self.defs.keys()):
                emitted += 1
                if ev_type == "effect":
                    kind, detail, line = payload
                    self.emit(type="effect", file=file, owner=owner,
                              kind=kind, detail=detail, line=line,
                              depth=depth, conditional=cond, loop=loop,
                              src=s[:4000], srcline=stmt_line)
                else:
                    name, line = payload
                    d = self.defs[name]
                    self.emit(type="call", file=file, owner=owner,
                              target=d["id"], detail=name, line=line,
                              depth=depth, conditional=cond, loop=loop,
                              src=s[:4000], srcline=stmt_line)
                    self.edges.add((owner, d["id"], cond))
                    if (name not in stack
                            and self.expansions.get(name, 0) < MAX_EXPANSIONS):
                        self.expansions[name] = self.expansions.get(name, 0) + 1
                        self.walk_span(d["body"], self.files[d["file"]].clean,
                                       d["body_off"], d["file"], d["id"],
                                       depth + 1, cond, loop, stack | {name})
            # A statement that produces no recognised effect or call still runs
            # (assignments, computations). It gets a quiet step of its own so
            # every executed line is accounted for in the coverage view.
            if emitted == 0:
                self.emit(type="stmt", file=file, owner=owner,
                          detail=" ".join(s.split())[:90], line=stmt_line,
                          depth=depth, conditional=cond, loop=loop,
                          src=s[:4000], srcline=stmt_line)

    # ------------------------------------------------------------------
    # Python
    # ------------------------------------------------------------------
    def walk_python(self, pf, owner, depth, cond, loop, stack):
        """Emit steps for a Python unit (file, embedded block or cell)."""
        if pf.tree is None:
            self.emit(type="note", file=pf.host, owner=owner, lang="python",
                      detail="Python could not be parsed (%s)" % pf.error,
                      line=pf.line_offset + 1, depth=depth,
                      conditional=cond, loop=loop)
            return
        self.walk_py_body(pf, pf.tree.body, owner, depth, cond, loop, stack)

    def walk_py_body(self, pf, body, owner, depth, cond, loop, stack):
        pending_imports = []

        def flush_imports():
            if not pending_imports:
                return
            names = []
            first = pending_imports[0]
            for nd in pending_imports:
                if isinstance(nd, ast.Import):
                    names += [a.name.split(".")[0] for a in nd.names]
                else:
                    names.append((nd.module or "").split(".")[0])
            uniq = sorted(set(n for n in names if n))
            self.emit(type="import", file=pf.host, owner=owner, lang="python",
                      detail=", ".join(uniq)[:120], line=pf.line(first),
                      depth=depth, conditional=cond, loop=loop,
                      src=pf.src(pending_imports[-1]), srcline=pf.line(first))
            del pending_imports[:]

        for node in body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                pending_imports.append(node)
                continue
            flush_imports()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                continue                      # definition, not execution
            line = pf.line(node)
            src = pf.src(node)
            if isinstance(node, ast.If):
                self.emit(type="branch", file=pf.host, owner=owner,
                          lang="python", detail=py_src_of(pf, node.test)[:60],
                          line=line, depth=depth, conditional=cond, loop=loop,
                          src=src, srcline=line)
                self.walk_py_body(pf, node.body, owner, depth + 1, True,
                                  loop, stack)
                if node.orelse:
                    self.walk_py_body(pf, node.orelse, owner, depth + 1, True,
                                      loop, stack)
                continue
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                kw = "While" if isinstance(node, ast.While) else "For"
                self.emit(type="loop", file=pf.host, owner=owner, lang="python",
                          detail=kw, line=line, depth=depth, conditional=cond,
                          loop=loop, src=src, srcline=line)
                self.walk_py_body(pf, node.body, owner, depth + 1, cond, True,
                                  stack)
                continue
            if isinstance(node, (ast.Try, ast.With, ast.AsyncWith)):
                self.walk_py_body(pf, node.body, owner, depth, cond, loop,
                                  stack)
                continue
            self.walk_py_stmt(pf, node, owner, depth, cond, loop, stack,
                              line, src)
        flush_imports()

    def walk_py_stmt(self, pf, node, owner, depth, cond, loop, stack,
                     line, src):
        """Effects and calls inside a single Python statement."""
        before = len(self.steps)
        self._walk_py_stmt_inner(pf, node, owner, depth, cond, loop, stack,
                                 line, src)
        if len(self.steps) == before:      # silent statement - still runs
            self.emit(type="stmt", file=pf.host, owner=owner, lang="python",
                      detail=" ".join(src.split())[:90], line=line,
                      depth=depth, conditional=cond, loop=loop,
                      src=src, srcline=line)

    def _walk_py_stmt_inner(self, pf, node, owner, depth, cond, loop, stack,
                            line, src):
        for call in py_scan_calls(node):
            fname = py_name(call.func)
            short = fname.split(".")[-1]
            root = fname.split(".")[0]
            cline = pf.line(call)
            # a call into another function of this script
            d = self.defs.get(short) or self.defs.get(fname)
            if d is not None and d.get("lang") == "python":
                self.emit(type="call", file=pf.host, owner=owner,
                          lang="python", target=d["id"], detail=short,
                          line=cline, depth=depth, conditional=cond,
                          loop=loop, src=src, srcline=line)
                self.edges.add((owner, d["id"], cond))
                if (short not in stack
                        and self.expansions.get(short, 0) < MAX_EXPANSIONS):
                    self.expansions[short] = self.expansions.get(short, 0) + 1
                    self.walk_py_body(pf, d["node"].body, d["id"], depth + 1,
                                      cond, loop, stack | {short})
                continue
            # Python -> JSL bridge
            if short in ("run_jsl", "submit") and root in ("jmp", "jsl"):
                self.emit(type="jslblock", file=pf.host, owner=owner,
                          lang="jsl", detail="", line=cline, depth=depth,
                          conditional=cond, loop=loop, src=src, srcline=line)
                code_val = py_str_arg(call)
                if code_val:
                    off = pf.line(call.args[0])
                    if code_val.startswith("\n"):
                        off += 1
                    self.walk_embedded_jsl(code_val, pf.host, owner,
                                           depth + 1, cond, loop, stack, off)
                continue
            kind = ""
            detail = ""
            if short in PY_FUNC_EFFECTS and (
                    root in ("", short) or root in PY_PLOT_MODULES
                    or root in ("pd", "pandas", "np", "jmp", "jmputils")):
                kind = PY_FUNC_EFFECTS[short]
                detail = py_str_arg(call)[:80] or short
            if not kind and short in PY_METHOD_EFFECTS:
                kind = PY_METHOD_EFFECTS[short]
                detail = py_str_arg(call)[:80] or short
            if not kind and root in PY_PLOT_MODULES:
                kind, detail = "plot", short
            if fname in ("jmp.open", "jmp.DataTable") or short == "DataTable":
                kind = "table"
                detail = py_str_arg(call)[:80] or short
            if short == "jpip":
                kind = "pkg"
                detail = " ".join(a.value for a in call.args
                                  if isinstance(a, ast.Constant)
                                  and isinstance(a.value, str))[:80]
            if kind:
                if kind == "model":
                    detail = py_model_label(pf, call)
                self.emit(type="effect", file=pf.host, owner=owner,
                          lang="python", kind=kind, detail=detail, line=cline,
                          depth=depth, conditional=cond, loop=loop,
                          src=src, srcline=line)

    def walk_embedded_jsl(self, code, host, owner, depth, cond, loop, stack,
                          line_offset):
        """Walk a JSL snippet that lives inside a Python string."""
        jf = JslFile(host + " (JSL)", code)
        extract_defs(jf)
        for name, d in jf.defs.items():
            d["file"] = host
            d["line"] += line_offset - 1
            if d.get("endline"):
                d["endline"] += line_offset - 1
            self.defs.setdefault(name, d)
        self.files.setdefault(jf.name, jf)
        base = len(self.steps)
        self.walk_span(jf.top_span, jf.top_span, 0, host, owner,
                       depth, cond, loop, stack)
        for st in self.steps[base:]:            # map onto the real file
            for k in ("line", "srcline"):
                if st.get(k):
                    st[k] += line_offset - 1

    # ------------------------------------------------------------------
    # Notebook
    # ------------------------------------------------------------------
    def walk_notebook(self, nb, owner, depth, stack):
        for cell in nb.cells:
            if cell["type"] == "Section":
                self.emit(type="section", file=nb.name, owner=owner,
                          lang="text", detail=cell["title"] or "Section",
                          line=cell["line"], depth=depth,
                          conditional=False, loop=False)
                continue
            if cell["type"] == "Text":
                txt = " ".join(cell["content"].split())[:110]
                self.emit(type="text", file=nb.name, owner=owner, lang="text",
                          detail=txt, line=cell["line"], depth=depth,
                          conditional=False, loop=False,
                          src=cell["content"][:2000],
                          srcline=cell["content_line"])
                continue
            lang = cell["lang"]
            self.emit(type="cell", file=nb.name, owner=owner, lang=lang,
                      detail=cell["title"] or ("%s cell" % lang.upper()),
                      line=cell["line"], depth=depth, conditional=False,
                      loop=False, hidden=cell["hidden"],
                      src=cell["content"][:4000],
                      srcline=cell["content_line"])
            if lang == "python":
                pf = PyFile(nb.name + " (Python)", cell["content"],
                            line_offset=cell["content_line"] - 1, host=nb.name)
                for nm, d in pf.defs.items():
                    self.defs.setdefault(nm, d)
                self.walk_python(pf, owner, depth + 1, False, False, stack)
            elif lang == "jsl":
                self.walk_embedded_jsl(cell["content"], nb.name, owner,
                                       depth + 1, False, False, stack,
                                       cell["content_line"])

    # ------------------------------------------------------------------
    def run(self, root_files):
        """Walk each independent root script (entry first, then any file
        that is neither the entry nor included by another file)."""
        root, top_id = "", ""
        try:
            for root in root_files:
                f = self.files[root]
                top_id = f"{root}::__top__"
                self.walked_includes.add(root)
                self.emit(type="start", file=root, owner=top_id,
                          detail=root, line=1, depth=0, conditional=False,
                          loop=False, lang=getattr(f, "lang", "jsl"))
                if isinstance(f, NotebookFile):
                    self.walk_notebook(f, top_id, 0, set())
                elif isinstance(f, PyFile):
                    self.walk_python(f, top_id, 0, False, False, set())
                else:
                    self.walk_span(f.top_span, f.top_span, 0, root, top_id,
                                   0, False, False, set())
        except OverflowError:
            # append directly: emit() would raise again at the limit
            self.steps.append(dict(type="note", file=root, owner=top_id,
                                   detail="step limit reached", line=0,
                                   depth=0, conditional=False, loop=False,
                                   i=len(self.steps)))


# ----------------------------------------------------------------------
# Inputs
# ----------------------------------------------------------------------

def load_jmpaddin(path):
    """Extract .jsl files and entry-point hints from a .jmpaddin archive."""
    tmp = tempfile.mkdtemp(prefix="flowlens_")
    entries = []
    files = {}
    meta = {}
    with zipfile.ZipFile(path) as z:
        z.extractall(tmp)
    for root, _, names in os.walk(tmp):
        for n in names:
            p = os.path.join(root, n)
            if n.lower().endswith(".jsl"):
                with open(p, encoding="utf-8", errors="replace") as fh:
                    files[n] = fh.read()
            elif n.lower().endswith(".jmpcust"):
                try:
                    txt = open(p, encoding="utf-8", errors="replace").read()
                    for m in re.finditer(r'type="path">([^<]+)</', txt):
                        entries.append(os.path.basename(m.group(1)))
                except Exception:
                    pass
            elif n.lower() == "addin.def":
                for ln in open(p, encoding="utf-8", errors="replace"):
                    if "=" in ln:
                        k, v = ln.split("=", 1)
                        meta[k.strip()] = v.strip()
    return files, entries, meta


def code_ranges_of(f):
    """Line spans holding analysable code, each with its own language."""
    if isinstance(f, NotebookFile):
        out = []
        for cell in f.cells:
            if cell["lang"] in ("python", "jsl") and cell["content"]:
                start = cell["content_line"]
                out.append({"from": start,
                            "to": start + cell["content"].count("\n"),
                            "lang": cell["lang"]})
        return out
    return [{"from": 1, "to": f.raw.count("\n") + 1,
             "lang": getattr(f, "lang", "jsl")}]


def make_file(name, code):
    """File object for the language of `name` / `code`."""
    lang = detect_lang(name, code)
    if lang == "python":
        return PyFile(name, code)
    if lang == "notebook":
        return NotebookFile(name, code)
    f = JslFile(name, code)
    extract_defs(f)
    extract_variables(f)
    return f


def build_model(sources, entry=None, addin_meta=None):
    files = {n: make_file(n, code) for n, code in sources.items()}
    all_defs = {}
    for f in files.values():
        all_defs.update(f.defs)

    # Notebook cells can define functions too - collect them so calls
    # between cells resolve.
    for f in list(files.values()):
        if isinstance(f, NotebookFile):
            for cell in f.cells:
                if cell["lang"] == "python" and cell["content"]:
                    pf = PyFile(f.name + " (Python)", cell["content"],
                                line_offset=cell["content_line"] - 1,
                                host=f.name)
                    all_defs.update(pf.defs)

    # Classify trivial helpers: tiny body, no side effects, no calls to
    # other defined functions (e.g. formatters like pad2). The UI can
    # de-emphasize these so they don't look like major workflow steps.
    for d in all_defs.values():
        if d.get("lang") == "python":
            node = d.get("node")
            body_src = d.get("src", "")
            calls_other = any(
                re.search(r"\b" + re.escape(n) + r"\s*\(", body_src)
                for n in all_defs if n != d["name"])
            has_effect = bool(re.search(
                r"\b(new_column|DataTable|open|to_csv|savefig|fit|predict|"
                r"run_jsl|print)\s*\(", body_src))
            has_flow = node is not None and any(
                isinstance(x, (ast.If, ast.For, ast.While, ast.Try))
                for x in ast.walk(node))
            d["helper"] = (len(body_src.strip()) < 220 and not calls_other
                           and not has_effect and not has_flow)
            continue
        body = d["body"]
        calls_other = any(
            re.search(r"\b" + re.escape(n) + r"\s*\(", body)
            for n in all_defs if n != d["name"])
        has_effect = any(
            kind != "log" and rx.search(body)
            for kind, rx in EFFECT_PATTERNS)
        has_flow = re.search(r"\b(If|For|While|Try)\s*\(", body) is not None
        d["helper"] = (len(body.strip()) < 220 and not calls_other
                       and not has_effect and not has_flow)

    included = {os.path.basename(i) for f in files.values() for i in f.includes}
    if entry is None:
        candidates = [n for n in files if n not in included]
        entry = candidates[0] if candidates else next(iter(files))

    df_vars, df_flows = extract_dataflow(files, all_defs)

    roots = [entry] + [n for n in files
                       if n != entry and n not in included]
    w = Walker(files, all_defs)
    w.run(roots)

    # Collapse identical consecutive steps (e.g. the same helper called
    # four times in a row) into one step with a repeat count.
    collapsed = []
    for s in w.steps:
        prev = collapsed[-1] if collapsed else None
        key = lambda x: (x["type"], x["owner"], x.get("target"),
                         x.get("kind"), x.get("detail"), x.get("src"))
        if prev and key(prev) == key(s):
            prev["count"] = prev.get("count", 1) + 1
        else:
            s["count"] = 1
            collapsed.append(s)
    for idx, s in enumerate(collapsed):
        s["i"] = idx
    w.steps = collapsed

    model = {
        "meta": {
            "tool": "JSL FlowLens",
            "version": VERSION,
            "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "addin": addin_meta or {},
        },
        "entry": entry,
        # Full source per file so the viewer can point at the exact lines
        "files": [{
            "name": f.name,
            "header": f.header,
            "lang": getattr(f, "lang", "jsl"),
            "n_lines": f.raw.count("\n") + 1,
            # line spans that hold analysable code - the whole file, except in
            # notebooks where only the code cells count
            "code_ranges": code_ranges_of(f),
            "includes": f.includes,
            "source": f.raw[:MAX_EMBED_CHARS],
            "truncated": len(f.raw) > MAX_EMBED_CHARS,
        } for f in files.values() if not f.name.endswith((" (JSL)", " (Python)"))],
        "functions": [{
            "id": d["id"], "name": d["name"], "kind": d["kind"],
            "file": d["file"], "args": d.get("args", []), "line": d["line"],
            "endline": d.get("endline", d["line"]), "doc": d.get("doc", ""),
            "src": d.get("src", ""), "helper": d.get("helper", False),
            "lang": d.get("lang", "jsl"),
        } for d in all_defs.values()],
        "variables": [v for f in files.values() for v in f.variables],
        "edges": [{"from": a, "to": b, "conditional": c} for a, b, c in sorted(w.edges)],
        "steps": w.steps,
        # variables as graph items, with directed read/write links
        "vars": sorted(df_vars.values(), key=lambda v: (v["file"], v["line"])),
        "flows": [{"from": a, "var": b, "kind": c} for a, b, c in sorted(df_flows)],
    }
    return model


def native_path(p):
    """Convert a JMP-style path (/C:/Users/...) to a native OS path."""
    p = (p or "").strip()
    if len(p) > 2 and p[0] == "/" and p[2] == ":":
        p = p[1:]
    return p


def run_simple(files_str="", addin_path="", pasted="", entry="",
               template="", out=""):
    """Single-call entry point for JMP's embedded Python.

    files_str: newline-separated absolute paths of .jsl files (may be "").
    addin_path: path to a .jmpaddin archive (may be "").
    pasted: raw JSL code pasted by the user (may be "").
    entry: preferred entry file name (may be "" for auto-detection).
    template: path of the HTML template; out: path of the HTML output.
    Returns the output path.
    """
    addin_path, template, out = (native_path(addin_path),
                                 native_path(template), native_path(out))
    sources, entries, meta = {}, [], None
    if addin_path:
        sources, entries, meta = load_jmpaddin(addin_path)
    if files_str:
        for p in files_str.splitlines():
            p = native_path(p)
            if p:
                with open(p, encoding="utf-8", errors="replace") as fh:
                    sources[os.path.basename(p)] = fh.read()
    if pasted and pasted.strip():
        sources["Pasted code.jsl"] = pasted
    if not sources:
        raise ValueError("no input sources")

    entry = entry.strip() if entry else ""
    if entry not in sources:
        entry = entries[0] if entries and entries[0] in sources else None

    model = build_model(sources, entry=entry, addin_meta=meta)
    tpl = open(template, encoding="utf-8").read()
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(tpl.replace("__MODEL_JSON__",
                             json.dumps(model, ensure_ascii=False)))
    return out


# ----------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="JSL FlowLens parser")
    ap.add_argument("inputs", nargs="+", help=".jsl files or one .jmpaddin")
    ap.add_argument("--entry", help="entry file name")
    ap.add_argument("--template", help="HTML template with __MODEL_JSON__ marker")
    ap.add_argument("-o", "--output", help="output file (.html or .json)")
    args = ap.parse_args(argv)

    addin_meta = None
    entry = args.entry
    if len(args.inputs) == 1 and args.inputs[0].lower().endswith(".jmpaddin"):
        sources, entries, addin_meta = load_jmpaddin(args.inputs[0])
        if not entry and entries:
            entry = entries[0]
    else:
        sources = {}
        for p in args.inputs:
            with open(p, encoding="utf-8", errors="replace") as fh:
                sources[os.path.basename(p)] = fh.read()

    model = build_model(sources, entry=entry, addin_meta=addin_meta)
    js = json.dumps(model, ensure_ascii=False, indent=None)

    if args.template:
        tpl = open(args.template, encoding="utf-8").read()
        out = tpl.replace("__MODEL_JSON__", js)
        path = args.output or "flowlens_output.html"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(out)
        print(f"wrote {path} ({len(model['steps'])} steps, "
              f"{len(model['functions'])} functions)")
    else:
        path = args.output
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(js)
            print(f"wrote {path}")
        else:
            print(js)


if __name__ == "__main__":
    main()
