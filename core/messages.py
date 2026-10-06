"""Structured assessment messages.

Rules produce these objects; rendering (traffic-light emoji + Markdown) is a
presentation step, so a web client can style ``kind`` itself and key on ``code``.
``text``/``detail`` may contain inline ``**bold**`` Markdown and nothing else.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Kind = Literal["critical", "warning", "caution", "ok", "unknown"]

ICONS = {"critical": "🔴", "warning": "🟡", "caution": "🟡", "ok": "🟢", "unknown": "⚪"}
_ICON_KINDS = (("🔴", "critical"), ("🟡", "warning"), ("🟢", "ok"), ("⚪", "unknown"))


def icon(kind: str) -> str:
    return ICONS.get(kind, "⚪")


def kind_of_label(label: str) -> str:
    """Severity of a rendered status label (legacy ``(area, "🔴 ...", detail)`` tuples)."""
    return next((k for ic, k in _ICON_KINDS if ic in label), "unknown")


@dataclass(frozen=True)
class Message:
    kind: str
    text: str
    code: str = ""

    def md(self) -> str:
        return f"{icon(self.kind)} {self.text}"

    @property
    def plain(self) -> str:
        return self.text.replace("**", "")


@dataclass(frozen=True)
class Finding:
    area: str
    kind: str
    status: str
    detail: str
    code: str = ""

    def row(self) -> tuple[str, str, str]:
        return (self.area, f"{icon(self.kind)} {self.status}", self.detail)


@dataclass(frozen=True)
class Action:
    area: str
    action: str
    code: str = ""

    def row(self) -> dict:
        return {"Area": self.area, "Recommended action": self.action}
