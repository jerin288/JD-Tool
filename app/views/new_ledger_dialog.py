"""Modal dialog for creating a ledger in Tally Prime."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from app.views.theme import INPUT_STYLE, button_style, color

PARENT_GROUP_CHOICES = (
    "Sundry Debtors",
    "Sundry Creditors",
    "Bank Accounts",
    "Cash-in-Hand",
    "Current Assets",
    "Current Liabilities",
    "Expenses",
    "Indirect Expenses",
    "Direct Expenses",
    "Income",
)


class NewLedgerDialog(ctk.CTkToplevel):
    """Collect a ledger name and existing Tally parent group."""

    def __init__(
        self,
        master: tk.Misc,
        on_submit: Callable[[str, str], None],
    ) -> None:
        super().__init__(master)
        self.title("New Ledger")
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._on_submit = on_submit

        ctk.CTkLabel(
            self,
            text="Create ledger in Tally Prime",
            font=ctk.CTkFont(size=16, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 8))

        ctk.CTkLabel(
            self,
            text="Ledger name",
            anchor="w",
            text_color=color("text_secondary"),
        ).pack(fill="x", padx=20)
        self.ledger_name = ctk.CTkEntry(self, placeholder_text="e.g. Demo Traders", width=360, height=32, **INPUT_STYLE)
        self.ledger_name.pack(fill="x", padx=20, pady=(4, 12))

        ctk.CTkLabel(
            self,
            text="Parent group (must already exist in Tally)",
            anchor="w",
            text_color=color("text_secondary"),
        ).pack(fill="x", padx=20)
        self.parent_group = ctk.CTkComboBox(
            self,
            values=list(PARENT_GROUP_CHOICES),
            state="normal",
            width=360,
            height=32,
            **INPUT_STYLE,
        )
        self.parent_group.set(PARENT_GROUP_CHOICES[0])
        self.parent_group.pack(fill="x", padx=20, pady=(4, 6))

        self.error_label = ctk.CTkLabel(
            self,
            text="",
            anchor="w",
            text_color=color("danger"),
            font=ctk.CTkFont(size=12),
        )
        self.error_label.pack(fill="x", padx=20, pady=(0, 4))

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(4, 18))
        ctk.CTkButton(
            actions,
            text="Cancel",
            width=90,
            command=self.destroy,
            **button_style("secondary"),
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(
            actions,
            text="Create",
            width=90,
            command=self._submit,
            **button_style("primary"),
        ).pack(side="right")

        self.ledger_name.focus_set()
        self.ledger_name.bind("<Return>", lambda _event: self._submit())
        self.after(20, self._center)
        self.grab_set()

    def _submit(self) -> None:
        name = self.ledger_name.get().strip()
        parent = self.parent_group.get().strip()
        if not name:
            self.error_label.configure(text="Enter a ledger name.")
            return
        if not parent:
            self.error_label.configure(text="Enter a parent group.")
            return
        self.grab_release()
        self.destroy()
        self._on_submit(name, parent)

    def _center(self) -> None:
        self.update_idletasks()
        master = self.master
        x = master.winfo_rootx() + max(0, (master.winfo_width() - self.winfo_width()) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")
