"""Shared helpers for the notebook frontend."""
from __future__ import annotations


def rgb_to_hex(rgb: tuple) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(rgb[0]), int(rgb[1]), int(rgb[2]))


def hex_to_rgb(hex_str: str) -> tuple:
    h = hex_str.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _th(text: str) -> str:
    return (
        f"<th style='text-align:left;padding:3px 12px 3px 0;"
        f"color:#888;border-bottom:1px solid #333'>{text}</th>"
    )


def _td(text: str, style: str = "") -> str:
    base = "padding:3px 12px 3px 0;color:#ccc"
    s = f"{base};{style}" if style else base
    return f"<td style='{s}'>{text}</td>"


def html_table(headers: list[str], rows: list[list[str]], max_height: int = 300) -> str:
    head = "<tr>" + "".join(_th(h) for h in headers) + "</tr>"
    body = "".join(
        "<tr>" + "".join(_td(cell) for cell in row) + "</tr>"
        for row in rows
    )
    return (
        f"<div style='max-height:{max_height}px;overflow-y:auto;"
        f"background:#1a1a1a;padding:8px;border-radius:4px'>"
        f"<table style='border-collapse:collapse;font-size:13px'>"
        f"{head}{body}</table></div>"
    )
