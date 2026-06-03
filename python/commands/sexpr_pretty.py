"""KiCad S-expression pretty-printer (token-preserving).

kicad-skip's ``Schematic.write()`` and the ``sexpdata.dumps`` write paths emit
the whole ``.kicad_sch`` on a single line. KiCad reads that fine (the format is
whitespace-insensitive) but it makes git diffs unusable and does not match the
canonical multi-line layout eeschema produces.

``format_kicad_sch_file`` re-indents such a file into KiCad-canonical multi-line
style **without changing a single token**. It tokenizes the file, re-emits it
pretty, then re-tokenizes the result and refuses to write unless the token tree
is byte-for-byte identical to the original. Worst case it is a no-op; it can
never corrupt or alter the design.

Patch: posture-football-pod project. See repo-root PATCHES.md.
"""

from __future__ import annotations

from typing import List, Union

Node = Union[str, list]


def _tokenize(s: str) -> List[Node]:
    """Parse an s-expression string into nested lists. Atoms (incl. quoted
    strings) are kept as their exact source text so nothing is reformatted."""
    stack: List[list] = [[]]
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "(":
            new: list = []
            stack[-1].append(new)
            stack.append(new)
            i += 1
        elif c == ")":
            if len(stack) == 1:
                raise ValueError("unbalanced ')'")
            stack.pop()
            i += 1
        elif c.isspace():
            i += 1
        elif c == '"':
            # quoted string literal, kept verbatim including quotes/escapes
            j = i + 1
            buf = ['"']
            while j < n:
                ch = s[j]
                if ch == "\\" and j + 1 < n:
                    buf.append(ch)
                    buf.append(s[j + 1])
                    j += 2
                    continue
                buf.append(ch)
                j += 1
                if ch == '"':
                    break
            else:
                raise ValueError("unterminated string literal")
            stack[-1].append("".join(buf))
            i = j
        else:
            j = i
            while j < n and (not s[j].isspace()) and s[j] not in '()"':
                j += 1
            stack[-1].append(s[i:j])
            i = j
    if len(stack) != 1:
        raise ValueError("unbalanced '('")
    return stack[0]


def _fmt(node: Node, depth: int) -> str:
    if not isinstance(node, list):
        return node
    if not node:
        return "()"
    has_child_list = any(isinstance(c, list) for c in node)
    if not has_child_list:
        # leaf list — everything on one line, e.g. (at 1.27 2.54 0)
        return "(" + " ".join(_fmt(c, 0) for c in node) + ")"

    ind = "\t" * depth
    child_ind = "\t" * (depth + 1)
    head = node[0]
    line0 = "(" + _fmt(head, depth) if not isinstance(head, list) else "(" + _fmt(head, depth + 1)

    i = 1
    # leading atoms stay on the opening line (e.g. (property "Reference" "U1" ...)
    while i < len(node) and not isinstance(node[i], list):
        line0 += " " + _fmt(node[i], depth)
        i += 1

    lines = [line0]
    while i < len(node):
        lines.append(child_ind + _fmt(node[i], depth + 1))
        i += 1
    return "\n".join(lines) + "\n" + ind + ")"


def format_kicad_sexpr(text: str) -> str:
    """Return ``text`` pretty-printed in KiCad-canonical style.

    Raises ValueError if the input does not parse to exactly one top-level
    s-expression, or if the pretty output does not re-tokenize identically
    (the token-preserving guarantee)."""
    tree = _tokenize(text)
    if len(tree) != 1 or not isinstance(tree[0], list):
        raise ValueError("expected exactly one top-level s-expression")
    out = _fmt(tree[0], 0) + "\n"
    # token-preserving guarantee: re-parse and compare
    if _tokenize(out) != tree:
        raise ValueError("pretty output changed the token tree — refusing")
    return out


def format_kicad_sch_file(path: str) -> bool:
    """Pretty-print a .kicad_sch (or any KiCad s-expr) file in place.

    Returns True if reformatted, False if left unchanged. Never raises and
    never writes anything other than a token-identical reformat — on any
    problem the original file is left exactly as it was."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            original = f.read()
        pretty = format_kicad_sexpr(original)
        if pretty == original:
            return False
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(pretty)
        return True
    except Exception:
        # best-effort: formatting must never break a successful write
        return False
