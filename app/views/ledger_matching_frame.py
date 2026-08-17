"""Tally connection and ledger matching screen."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import customtkinter as ctk

from app.models.tally import TallyCompanyData, TallyConnectionResult


class LedgerMatchingFrame(ctk.CTkFrame):
    """Connect to Tally, choose a company and bank ledger, then run matching."""

    def __init__(
        self,
        master: tk.Misc,
        server_url: str,
        on_test: Callable[[str], None],
        on_load_company: Callable[[str], None],
        on_match: Callable[[str], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.on_test = on_test
        self.on_load_company = on_load_company
        self.on_match = on_match
        ctk.CTkLabel(self, text="Ledger Matching", font=ctk.CTkFont(size=29, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Connect only to the local Tally Prime HTTP server and match descriptions against the open company.",
            text_color=("#566170", "#a8b0bc"),
        ).pack(anchor="w", pady=(5, 18))

        connection = ctk.CTkFrame(self)
        connection.pack(fill="x")
        ctk.CTkLabel(connection, text="Tally server URL", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, padx=14, pady=(12, 3), sticky="w")
        ctk.CTkLabel(connection, text="Open company", font=ctk.CTkFont(weight="bold")).grid(row=0, column=2, padx=14, pady=(12, 3), sticky="w")
        self.url_entry = ctk.CTkEntry(connection, width=280)
        self.url_entry.insert(0, server_url)
        self.url_entry.grid(row=1, column=0, padx=14, pady=(0, 14), sticky="ew")
        self.test_button = ctk.CTkButton(connection, text="Test Tally Connection", width=175, command=lambda: self.on_test(self.url_entry.get()))
        self.test_button.grid(row=1, column=1, padx=(0, 14), pady=(0, 14))
        self.company_selector = ctk.CTkComboBox(connection, values=["No companies detected"], state="readonly", width=270)
        self.company_selector.set("No companies detected")
        self.company_selector.grid(row=1, column=2, padx=14, pady=(0, 14), sticky="ew")
        self.load_button = ctk.CTkButton(connection, text="Download Ledgers", width=150, command=lambda: self.on_load_company(self.company_selector.get()))
        self.load_button.grid(row=1, column=3, padx=(0, 14), pady=(0, 14))
        connection.grid_columnconfigure((0, 2), weight=1)
        self.connection_status = ctk.CTkLabel(connection, text="Not connected", anchor="w")
        self.connection_status.grid(row=2, column=0, columnspan=4, padx=14, pady=(0, 12), sticky="ew")

        matching = ctk.CTkFrame(self)
        matching.pack(fill="x", pady=12)
        ctk.CTkLabel(matching, text="Statement bank ledger", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=(14, 8), pady=12)
        self.bank_ledger_selector = ctk.CTkComboBox(matching, values=["Download ledgers first"], state="readonly", width=310)
        self.bank_ledger_selector.set("Download ledgers first")
        self.bank_ledger_selector.pack(side="left", pady=12)
        self.match_button = ctk.CTkButton(matching, text="Auto-match Transactions", width=180, command=lambda: self.on_match(self.bank_ledger_selector.get()))
        self.match_button.pack(side="left", padx=10)
        self.match_summary = ctk.CTkLabel(matching, text="No matching run yet")
        self.match_summary.pack(side="right", padx=14)

        ledger_panel = ctk.CTkFrame(self)
        ledger_panel.pack(fill="both", expand=True)
        ctk.CTkLabel(ledger_panel, text="Ledgers in selected company", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=12, pady=10)
        self.ledger_tree = ttk.Treeview(ledger_panel, columns=("name", "group"), show="headings")
        self.ledger_tree.heading("name", text="Ledger name")
        self.ledger_tree.heading("group", text="Parent group")
        self.ledger_tree.column("name", width=390)
        self.ledger_tree.column("group", width=280)
        scrollbar = ttk.Scrollbar(ledger_panel, orient="vertical", command=self.ledger_tree.yview)
        self.ledger_tree.configure(yscrollcommand=scrollbar.set)
        self.ledger_tree.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=(0, 12))
        scrollbar.pack(side="right", fill="y", padx=(0, 12), pady=(0, 12))

    def set_busy(self, busy: bool, message: str = "") -> None:
        state = "disabled" if busy else "normal"
        self.test_button.configure(state=state)
        self.load_button.configure(state=state)
        self.match_button.configure(state=state)
        if message:
            self.connection_status.configure(text=message)

    def show_connection(self, result: TallyConnectionResult) -> None:
        companies = [item.name for item in result.companies]
        if companies:
            self.company_selector.configure(values=companies)
            self.company_selector.set(companies[0])
            suffix = " Select one." if len(companies) > 1 else ""
            self.connection_status.configure(
                text=f"Connected in {result.response_time_ms} ms • {len(companies)} open company(s).{suffix}"
            )
        else:
            self.company_selector.configure(values=["No company is open"])
            self.company_selector.set("No company is open")
            self.connection_status.configure(text="Connected to Tally, but no company is open.")

    def show_company_data(self, data: TallyCompanyData, default_bank_ledger: str = "") -> None:
        self.ledger_tree.delete(*self.ledger_tree.get_children())
        for ledger in data.ledgers:
            self.ledger_tree.insert("", "end", values=(ledger.name, ledger.parent_group))
        bank_ledgers = [item.name for item in data.ledgers if item.is_bank_or_cash]
        choices = bank_ledgers or [item.name for item in data.ledgers]
        if choices:
            self.bank_ledger_selector.configure(values=choices)
            self.bank_ledger_selector.set(default_bank_ledger if default_bank_ledger in choices else choices[0])
        self.connection_status.configure(
            text=f"{data.company.name}: {len(data.ledgers):,} ledgers and {len(data.voucher_types)} voucher types downloaded."
        )

    def show_match_summary(self, counts: dict[str, int]) -> None:
        self.match_summary.configure(
            text=f"Matched {counts['matched']:,} • Rules {counts['rules']:,} • Suspense {counts['suspense']:,}"
        )
