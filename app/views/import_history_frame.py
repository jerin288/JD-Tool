"""Persisted Tally import history view."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import customtkinter as ctk

from app.models.export import ImportBatch
from app.views.theme import color


class ImportHistoryFrame(ctk.CTkFrame):
    def __init__(self, master: tk.Misc, list_history: Callable[[int], list[ImportBatch]]) -> None:
        super().__init__(master, fg_color="transparent")
        self.list_history = list_history
        self.batches: dict[str, ImportBatch] = {}
        ctk.CTkLabel(self, text="Import History", font=ctk.CTkFont(size=29, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Recent direct-import reports stored locally in SQLite.",
            text_color=color("text_muted"),
        ).pack(anchor="w", pady=(5, 16))
        body = ctk.CTkFrame(self, fg_color=color("surface"), border_width=1, border_color=color("separator"))
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            body,
            columns=("time", "company", "total", "created", "altered", "ignored", "failed"),
            show="headings",
            selectmode="browse",
        )
        headings = ("Time", "Company", "Requested", "Created", "Altered", "Ignored", "Failed")
        widths = (165, 260, 90, 80, 80, 80, 80)
        for column, heading, width in zip(self.tree["columns"], headings, widths, strict=False):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width)
        self.tree.pack(side="left", fill="both", expand=True, padx=10, pady=10)
        self.tree.bind("<<TreeviewSelect>>", self._show_details)
        self.details = ctk.CTkTextbox(body, width=430, wrap="word")
        self.details.pack(side="right", fill="y", padx=(0, 10), pady=10)
        self.refresh()

    def refresh(self) -> None:
        batches = self.list_history(100)
        self.batches = {item.id: item for item in batches}
        self.tree.delete(*self.tree.get_children())
        for item in batches:
            self.tree.insert(
                "",
                "end",
                iid=item.id,
                values=(
                    item.created_at.strftime("%Y-%m-%d %H:%M:%S"),
                    item.company_name,
                    item.total_vouchers,
                    item.created,
                    item.altered,
                    item.ignored,
                    item.failed,
                ),
            )

    def _show_details(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        item = self.batches[selected[0]]
        text = (
            f"Company: {item.company_name}\nRequested: {item.total_vouchers}\n"
            f"Created: {item.created}\nAltered: {item.altered}\nIgnored: {item.ignored}\n"
            f"Errors: {item.errors}\nFailed: {item.failed}\n\n"
            + ("\n".join(item.messages) if item.messages else "No error messages.")
        )
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
