"""Collapsible transaction, validation, and XML detail panel."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from tkinter import ttk

import customtkinter as ctk

from app.models.enums import DuplicateStatus, VoucherType
from app.models.export import ExportValidationReport
from app.models.transaction import Transaction
from app.utils.amounts import parse_decimal
from app.utils.ledger_names import is_numeric_ledger_reference
from app.views.theme import INPUT_STYLE, button_style, color


class TransactionDetailPanel(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        on_save: Callable[[Transaction], None],
        on_save_rule: Callable[[Transaction], None],
        on_ignore: Callable[[Transaction], None],
        on_delete: Callable[[Transaction], None],
        on_duplicate_status: Callable[[Transaction, DuplicateStatus], None],
        on_issue_selected: Callable[[str], None],
        on_close: Callable[[], None],
    ) -> None:
        super().__init__(
            master,
            width=370,
            corner_radius=6,
            fg_color=color("surface_secondary"),
            border_width=1,
            border_color=color("border"),
        )
        self.grid_propagate(False)
        self.on_save = on_save
        self.on_save_rule = on_save_rule
        self.on_ignore = on_ignore
        self.on_delete = on_delete
        self.on_duplicate_status = on_duplicate_status
        self.on_issue_selected = on_issue_selected
        self.transaction: Transaction | None = None
        self.entries: dict[str, ctk.CTkEntry | ctk.CTkComboBox] = {}
        self.issue_transactions: dict[str, str] = {}
        self._loading = False

        heading = ctk.CTkFrame(self, fg_color="transparent")
        heading.pack(fill="x", padx=8, pady=(7, 2))
        self.title = ctk.CTkLabel(heading, text="Transaction Details", font=ctk.CTkFont(size=14, weight="bold"))
        self.title.pack(side="left")
        ctk.CTkButton(heading, text="×", width=28, height=25, command=on_close, **button_style("secondary")).pack(
            side="right"
        )

        self.tabs = ctk.CTkTabview(self, command=lambda: None)
        self.tabs.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        details = self.tabs.add("Details")
        issues = self.tabs.add("Issues")
        preview = self.tabs.add("XML Preview")

        form = ctk.CTkScrollableFrame(details, fg_color="transparent")
        form.pack(fill="both", expand=True)
        self._entry_row(form, "transaction_date", "Date (YYYY-MM-DD)")
        self._entry_row(form, "value_date", "Value Date")
        self._entry_row(form, "description", "Description")
        self._entry_row(form, "narration", "Narration")
        self._entry_row(form, "reference_number", "Reference Number")
        self._entry_row(form, "cheque_number", "Cheque Number")
        self._entry_row(form, "debit_amount", "Debit")
        self._entry_row(form, "credit_amount", "Credit")
        self._entry_row(form, "balance", "Balance")
        self._combo_row(form, "opposite_ledger", "Opposite Ledger", [""])
        self._combo_row(form, "voucher_type", "Voucher Type", [item.value for item in VoucherType])
        self._read_only_row(form, "confidence", "Matching Confidence")
        self._read_only_row(form, "transaction_type", "Transaction Type")
        self._read_only_row(form, "instrument_date", "Instrument Date")
        self._read_only_row(form, "bank_name", "Bank Name")
        self._read_only_row(form, "branch_name", "Branch Name")
        self.message = ctk.CTkLabel(form, text="Select a transaction", anchor="w", text_color=color("text_muted"))
        self.message.pack(fill="x", padx=6, pady=5)
        actions = ctk.CTkFrame(form, fg_color="transparent")
        actions.pack(fill="x", padx=4, pady=5)
        ctk.CTkButton(actions, text="Save Changes", height=29, command=self.save, **button_style("primary")).pack(
            side="left", padx=2
        )
        ctk.CTkButton(
            actions, text="Save Match Rule", height=29, command=self._save_rule, **button_style("secondary")
        ).pack(side="left", padx=2)
        secondary = ctk.CTkFrame(form, fg_color="transparent")
        secondary.pack(fill="x", padx=4, pady=(0, 8))
        secondary.pack_propagate(True)
        for column in range(4):
            secondary.grid_columnconfigure(column, weight=1, uniform="detail_secondary", minsize=78)
        for column, (label, command) in enumerate(
            (
                ("Ignore", self._ignore),
                ("Delete", self._delete),
                ("Duplicate", lambda: self._duplicate(DuplicateStatus.CONFIRMED_DUPLICATE)),
                ("Unique", lambda: self._duplicate(DuplicateStatus.CONFIRMED_UNIQUE)),
            )
        ):
            ctk.CTkButton(
                secondary,
                text=label,
                width=80,
                height=27,
                command=command,
                **button_style("danger" if label == "Delete" else "secondary"),
            ).grid(row=0, column=column, padx=1, sticky="ew")

        self.issue_tree = ttk.Treeview(issues, columns=("row", "severity", "message"), show="headings")
        self.issue_tree.heading("row", text="Row")
        self.issue_tree.heading("severity", text="Level")
        self.issue_tree.heading("message", text="Message")
        self.issue_tree.column("row", width=45, anchor="center")
        self.issue_tree.column("severity", width=65)
        self.issue_tree.column("message", width=240)
        self.issue_tree.pack(fill="both", expand=True, padx=5, pady=5)
        self.issue_tree.bind("<Double-1>", self._open_issue)

        self.preview_text = ctk.CTkTextbox(preview, wrap="none", font=("Consolas", 10))
        self.preview_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.preview_text.insert("1.0", "Generate an XML preview from the bottom action bar.")
        self.preview_text.configure(state="disabled")

    def _entry_row(self, master: tk.Misc, field_name: str, label: str) -> None:
        ctk.CTkLabel(master, text=label, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=6, pady=(4, 0))
        entry = ctk.CTkEntry(master, height=28, **INPUT_STYLE)
        entry.pack(fill="x", padx=6)
        entry.bind("<FocusOut>", lambda _event: self.save(silent=True))
        self.entries[field_name] = entry

    def _combo_row(self, master: tk.Misc, field_name: str, label: str, values: list[str]) -> None:
        ctk.CTkLabel(master, text=label, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w", padx=6, pady=(4, 0))
        combo = ctk.CTkComboBox(
            master, values=values, height=28, command=lambda _value: self.save(silent=True), **INPUT_STYLE
        )
        combo.pack(fill="x", padx=6)
        self.entries[field_name] = combo

    def _read_only_row(self, master: tk.Misc, key: str, label: str) -> None:
        row = ctk.CTkFrame(master, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=2)
        ctk.CTkLabel(row, text=label, font=ctk.CTkFont(size=10, weight="bold")).pack(side="left")
        value = ctk.CTkLabel(row, text="—", anchor="e", text_color=color("text_secondary"))
        value.pack(side="right")
        setattr(self, f"{key}_value", value)

    def set_ledger_choices(self, ledgers: list[str]) -> None:
        combo = self.entries["opposite_ledger"]
        assert isinstance(combo, ctk.CTkComboBox)
        combo.configure(
            values=[name.strip() for name in ledgers if name.strip() and not is_numeric_ledger_reference(name)] or [""]
        )

    def load(self, transaction: Transaction, bank_name: str = "") -> None:
        self._loading = True
        self.transaction = transaction
        values = {
            "transaction_date": transaction.transaction_date.isoformat() if transaction.transaction_date else "",
            "value_date": transaction.value_date.isoformat() if transaction.value_date else "",
            "description": transaction.description,
            "narration": transaction.narration,
            "reference_number": transaction.reference_number,
            "cheque_number": transaction.cheque_number,
            "debit_amount": str(transaction.debit_amount),
            "credit_amount": str(transaction.credit_amount),
            "balance": "" if transaction.balance is None else str(transaction.balance),
            "opposite_ledger": transaction.opposite_ledger,
            "voucher_type": transaction.voucher_type.value,
        }
        for field_name, widget in self.entries.items():
            if isinstance(widget, ctk.CTkComboBox):
                widget.set(values[field_name])
            else:
                widget.delete(0, "end")
                widget.insert(0, values[field_name])
        self.title.configure(text=f"Transaction Details • Row {transaction.row_number}")
        self.confidence_value.configure(
            text=f"{transaction.matching_confidence:.0f}% ({transaction.matching_method or 'Unmatched'})"
        )
        self.transaction_type_value.configure(text=self._transaction_type(transaction))
        instrument = transaction.value_date or transaction.transaction_date
        self.instrument_date_value.configure(text=instrument.isoformat() if instrument else "—")
        self.bank_name_value.configure(text=bank_name or "—")
        self.branch_name_value.configure(text="Not available")
        self.message.configure(text=transaction.validation_message or "Ready")
        self._loading = False

    def save(self, silent: bool = False) -> None:
        if self._loading or self.transaction is None:
            return
        try:
            transaction = self.transaction
            transaction.transaction_date = self._date("transaction_date", required=True)
            transaction.value_date = self._date("value_date", required=False)
            transaction.description = self.entries["description"].get().strip()
            transaction.narration = self.entries["narration"].get().strip()
            transaction.reference_number = self.entries["reference_number"].get().strip()
            transaction.cheque_number = self.entries["cheque_number"].get().strip()
            transaction.debit_amount = parse_decimal(self.entries["debit_amount"].get())
            transaction.credit_amount = parse_decimal(self.entries["credit_amount"].get())
            balance = self.entries["balance"].get().strip()
            transaction.balance = parse_decimal(balance) if balance else None
            transaction.opposite_ledger = self.entries["opposite_ledger"].get().strip()
            transaction.voucher_type = VoucherType(self.entries["voucher_type"].get())
            if transaction.opposite_ledger:
                transaction.matching_confidence = Decimal("100")
                transaction.matching_method = "Manual"
            self.on_save(transaction)
            self.message.configure(text="✓ Changes saved", text_color=color("success"))
        except (ValueError, KeyError) as exc:
            self.message.configure(text=f"✕ {exc}", text_color=color("danger"))
            if not silent:
                self.tabs.set("Details")

    def _date(self, field_name: str, required: bool) -> object:
        raw = self.entries[field_name].get().strip()
        if not raw and not required:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("Dates must use YYYY-MM-DD format.") from exc

    def show_validation(self, report: ExportValidationReport, *, select_tab: bool = True) -> None:
        self.issue_tree.delete(*self.issue_tree.get_children())
        self.issue_transactions.clear()
        for index, issue in enumerate(report.issues):
            iid = f"issue-{index}"
            self.issue_transactions[iid] = issue.transaction_id
            self.issue_tree.insert("", "end", iid=iid, values=(issue.row_number, issue.severity, issue.message))
        if select_tab:
            self.tabs.set("Issues")

    def show_xml(self, xml_text: str) -> None:
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", xml_text)
        self.preview_text.configure(state="disabled")
        self.tabs.set("XML Preview")

    def _open_issue(self, _event: tk.Event) -> None:
        selected = self.issue_tree.selection()
        if selected and selected[0] in self.issue_transactions:
            self.on_issue_selected(self.issue_transactions[selected[0]])

    def _save_rule(self) -> None:
        if self.transaction:
            self.save(silent=True)
            self.on_save_rule(self.transaction)

    def _ignore(self) -> None:
        if self.transaction:
            self.on_ignore(self.transaction)

    def _delete(self) -> None:
        if self.transaction:
            self.on_delete(self.transaction)

    def _duplicate(self, status: DuplicateStatus) -> None:
        if self.transaction:
            self.on_duplicate_status(self.transaction, status)

    @staticmethod
    def _transaction_type(transaction: Transaction) -> str:
        text = transaction.description.upper()
        for name in ("UPI", "NEFT", "IMPS", "RTGS", "CHEQUE", "CASH"):
            if name in text:
                return name.title()
        return "Other"
