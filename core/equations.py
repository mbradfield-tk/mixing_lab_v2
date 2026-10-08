"""Equations Reference: parse ``data/equations.md`` into sections and entries.

Format (see the comment at the top of the file): ``# Section``, ``## Entry``, an optional
``Used in: A, B`` first line, a Markdown body whose first ``$$`` block is the headline
equation, and an optional trailing ``Sources:`` list of ``- `` bullets.
"""
from __future__ import annotations

import re
import unicodedata

_COMMENT = re.compile(r"<!--.*?-->", re.S)


def slug(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return s or "item"


def _split_equation(body: list[str]) -> tuple[str | None, list[str]]:
    """(first $$…$$ block, remaining lines)."""
    for i, line in enumerate(body):
        if line.strip() == "$$":
            for j in range(i + 1, len(body)):
                if body[j].strip() == "$$":
                    return "\n".join(body[i + 1:j]).strip(), body[:i] + body[j + 1:]
            break
    return None, body


def _entry(title: str, lines: list[str]) -> dict:
    while lines and not lines[0].strip():
        lines = lines[1:]
    used_in: list[str] = []
    if lines and lines[0].startswith("Used in:"):
        used_in = [u.strip() for u in lines[0][len("Used in:"):].split(",") if u.strip()]
        lines = lines[1:]
    sources: list[str] = []
    for i, line in enumerate(lines):
        if line.strip() == "Sources:":
            sources = [ln.strip()[2:].strip() for ln in lines[i + 1:] if ln.strip().startswith("- ")]
            lines = lines[:i]
            break
    equation, body = _split_equation(lines)
    return {"id": slug(title), "title": title, "used_in": used_in, "equation": equation,
            "body": "\n".join(body).strip(), "sources": sources}


def parse(text: str) -> dict:
    sections: list[dict] = []
    entry_title: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if not sections:
            return
        sec = sections[-1]
        if entry_title is None:
            sec["intro"] = "\n".join(buf).strip()
        else:
            entry = _entry(entry_title, buf)
            entry["id"] = f"{sec['id']}--{entry['id']}"
            sec["entries"].append(entry)

    for line in _COMMENT.sub("", text).splitlines():
        if line.startswith("# "):
            flush()
            title = line[2:].strip()
            sections.append({"id": slug(title), "title": title, "intro": "", "entries": []})
            entry_title, buf = None, []
        elif line.startswith("## "):
            flush()
            entry_title, buf = line[3:].strip(), []
        else:
            buf.append(line)
    flush()
    return {"sections": sections}
