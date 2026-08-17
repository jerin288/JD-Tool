"""Central visual theme for the desktop workspace.

Keep visual decisions in this module so every active panel has the same
contrast, spacing cues, and semantic status colours in light and dark modes.
"""

from __future__ import annotations

from typing import Any

COLORS = {
    "background": "#F4F6F8",
    "surface": "#FFFFFF",
    "surface_secondary": "#F8FAFC",
    "header": "#1E293B",
    "header_text": "#FFFFFF",
    "header_muted": "#CBD5E1",
    "text_primary": "#1F2937",
    "text_secondary": "#475569",
    "text_muted": "#64748B",
    "border": "#CBD5E1",
    "separator": "#E2E8F0",
    "primary": "#2563EB",
    "primary_hover": "#1D4ED8",
    "success": "#15803D",
    "success_hover": "#166534",
    "warning": "#B45309",
    "danger": "#B91C1C",
    "danger_hover": "#991B1B",
    "info": "#1D4ED8",
    "disabled_background": "#E5E7EB",
    "disabled_text": "#9CA3AF",
    "table_header": "#334155",
    "table_header_text": "#FFFFFF",
    "table_alternate": "#F8FAFC",
    "table_selected": "#DBEAFE",
    "table_selected_text": "#1E3A8A",
    "success_background": "#DCFCE7",
    "warning_background": "#FEF3C7",
    "danger_background": "#FEE2E2",
    "info_background": "#DBEAFE",
    "unmatched_background": "#FFF7ED",
    "duplicate_background": "#FFEDD5",
}

DARK_COLORS = {
    "background": "#0F172A",
    "surface": "#111827",
    "surface_secondary": "#1E293B",
    "header": "#0F172A",
    "header_text": "#F8FAFC",
    "header_muted": "#CBD5E1",
    "text_primary": "#F8FAFC",
    "text_secondary": "#CBD5E1",
    "text_muted": "#94A3B8",
    "border": "#475569",
    "separator": "#334155",
    "primary": "#3B82F6",
    "primary_hover": "#2563EB",
    "success": "#4ADE80",
    "success_hover": "#22C55E",
    "warning": "#FBBF24",
    "danger": "#F87171",
    "danger_hover": "#EF4444",
    "info": "#60A5FA",
    "disabled_background": "#374151",
    "disabled_text": "#9CA3AF",
    "table_header": "#334155",
    "table_header_text": "#FFFFFF",
    "table_alternate": "#172033",
    "table_selected": "#1E3A5F",
    "table_selected_text": "#DBEAFE",
    "success_background": "#14532D",
    "warning_background": "#713F12",
    "danger_background": "#7F1D1D",
    "info_background": "#1E3A8A",
    "unmatched_background": "#431407",
    "duplicate_background": "#7C2D12",
}


def color(name: str) -> tuple[str, str]:
    """Return the CustomTkinter light/dark colour pair for *name*."""

    return COLORS[name], DARK_COLORS[name]


def button_style(kind: str = "primary") -> dict[str, Any]:
    """Return consistent options for a semantic button category."""

    common: dict[str, Any] = {
        "border_width": 1,
        "text_color_disabled": color("disabled_text"),
    }
    if kind == "success":
        return {
            **common,
            "fg_color": color("success"),
            "hover_color": color("success_hover"),
            "border_color": color("success"),
            "text_color": color("header_text"),
        }
    if kind == "danger":
        return {
            **common,
            "fg_color": color("danger"),
            "hover_color": color("danger_hover"),
            "border_color": color("danger"),
            "text_color": color("header_text"),
        }
    if kind == "secondary":
        return {
            **common,
            "fg_color": color("surface"),
            "hover_color": color("surface_secondary"),
            "border_color": color("border"),
            "text_color": color("text_primary"),
        }
    return {
        **common,
        "fg_color": color("primary"),
        "hover_color": color("primary_hover"),
        "border_color": color("primary"),
        "text_color": color("header_text"),
    }


INPUT_STYLE = {
    "fg_color": color("surface"),
    "border_color": color("border"),
    "text_color": color("text_primary"),
}
