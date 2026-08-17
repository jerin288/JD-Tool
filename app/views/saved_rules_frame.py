"""Saved ledger matching rule editor."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from tkinter import messagebox, ttk
from uuid import uuid4

import customtkinter as ctk

from app.models.enums import RuleMatchType, VoucherType
from app.models.matching_rule import MatchingRule
from app.utils.ledger_names import LEGACY_LEDGER_LABEL, is_numeric_ledger_reference
from app.views.theme import INPUT_STYLE, button_style, color


class SavedRulesFrame(ctk.CTkFrame):
    """Create, update, enable, and delete description matching rules."""

    def __init__(
        self,
        master: tk.Misc,
        list_rules: Callable[[], list[MatchingRule]],
        on_save: Callable[[MatchingRule], None],
        on_delete: Callable[[str], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.list_rules = list_rules
        self.on_save = on_save
        self.on_delete = on_delete
        self.rules: dict[str, MatchingRule] = {}
        self.selected_rule_id = ""
        self.ledger_names: list[str] = []
        ctk.CTkLabel(self, text="Saved Rules", font=ctk.CTkFont(size=29, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Rules run before all automatic matching methods and are reused on future imports.",
            text_color=color("text_muted"),
        ).pack(anchor="w", pady=(5, 18))

        form = ctk.CTkFrame(self, fg_color=color("surface_secondary"), border_width=1, border_color=color("separator"))
        form.pack(fill="x")
        labels = ("Description pattern", "Match type", "Tally ledger", "Voucher type", "Priority")
        for column, label in enumerate(labels):
            ctk.CTkLabel(form, text=label, font=ctk.CTkFont(size=12, weight="bold")).grid(
                row=0, column=column, padx=8, pady=(10, 3), sticky="w"
            )
            form.grid_columnconfigure(column, weight=2 if column in {0, 2} else 1)
        self.pattern_entry = ctk.CTkEntry(form, placeholder_text="e.g. DEMO TRADERS", **INPUT_STYLE)
        self.pattern_entry.grid(row=1, column=0, padx=8, pady=(0, 12), sticky="ew")
        self.match_type = ctk.CTkComboBox(
            form, values=[item.value for item in RuleMatchType], state="readonly", **INPUT_STYLE
        )
        self.match_type.set(RuleMatchType.CONTAINS.value)
        self.match_type.grid(row=1, column=1, padx=8, pady=(0, 12), sticky="ew")
        self.ledger_selector = ctk.CTkComboBox(form, values=["Download Tally ledgers first"], **INPUT_STYLE)
        self.ledger_selector.set("Download Tally ledgers first")
        self.ledger_selector.grid(row=1, column=2, padx=8, pady=(0, 12), sticky="ew")
        self.voucher_type = ctk.CTkComboBox(
            form, values=[item.value for item in VoucherType], state="readonly", **INPUT_STYLE
        )
        self.voucher_type.set(VoucherType.UNASSIGNED.value)
        self.voucher_type.grid(row=1, column=3, padx=8, pady=(0, 12), sticky="ew")
        self.priority_entry = ctk.CTkEntry(form, width=80, **INPUT_STYLE)
        self.priority_entry.insert(0, "100")
        self.priority_entry.grid(row=1, column=4, padx=8, pady=(0, 12), sticky="ew")
        self.enabled_switch = ctk.CTkSwitch(form, text="Enabled")
        self.enabled_switch.select()
        self.enabled_switch.grid(row=1, column=5, padx=8, pady=(0, 12))
        ctk.CTkButton(form, text="Save Rule", width=100, command=self._save, **button_style("primary")).grid(
            row=1, column=6, padx=8, pady=(0, 12)
        )
        ctk.CTkButton(form, text="Clear", width=70, command=self.clear_form, **button_style("secondary")).grid(
            row=1, column=7, padx=(0, 8), pady=(0, 12)
        )

        self.tree = ttk.Treeview(
            self,
            columns=("pattern", "type", "ledger", "voucher", "priority", "enabled", "uses"),
            show="headings",
            selectmode="browse",
        )
        headings = ("Pattern", "Match type", "Ledger", "Voucher", "Priority", "Enabled", "Uses")
        widths = (240, 140, 240, 110, 75, 75, 65)
        for column, heading, width in zip(self.tree["columns"], headings, widths, strict=False):
            self.tree.heading(column, text=heading)
            self.tree.column(column, width=width)
        self.tree.pack(fill="both", expand=True, pady=12)
        self.tree.bind("<<TreeviewSelect>>", self._load_selected)
        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x")
        ctk.CTkButton(controls, text="Delete Selected Rule", command=self._delete, **button_style("danger")).pack(
            side="right"
        )
        self.refresh()

    def set_ledgers(self, ledger_names: list[str]) -> None:
        self.ledger_names = sorted(
            {name.strip() for name in ledger_names if name.strip() and not is_numeric_ledger_reference(name)},
            key=str.lower,
        )
        values = self.ledger_names or ["Download Tally ledgers first"]
        self.ledger_selector.configure(values=values)
        if self.ledger_selector.get() not in values:
            self.ledger_selector.set(values[0])

    def refresh(self) -> None:
        rules = self.list_rules()
        self.rules = {item.id: item for item in rules}
        self.tree.delete(*self.tree.get_children())
        for rule in rules:
            self.tree.insert(
                "",
                "end",
                iid=rule.id,
                values=(
                    rule.pattern,
                    rule.match_type.value,
                    rule.ledger_name or LEGACY_LEDGER_LABEL,
                    rule.voucher_type.value,
                    rule.priority,
                    "Yes" if rule.enabled else "No",
                    rule.use_count,
                ),
            )

    def clear_form(self) -> None:
        self.selected_rule_id = ""
        self.pattern_entry.delete(0, "end")
        self.match_type.set(RuleMatchType.CONTAINS.value)
        self.voucher_type.set(VoucherType.UNASSIGNED.value)
        self.priority_entry.delete(0, "end")
        self.priority_entry.insert(0, "100")
        self.enabled_switch.select()

    def _save(self) -> None:
        try:
            priority = int(self.priority_entry.get())
        except ValueError:
            messagebox.showerror("Invalid priority", "Priority must be a whole number.", parent=self)
            return
        existing = self.rules.get(self.selected_rule_id)
        rule = MatchingRule(
            id=existing.id if existing else str(uuid4()),
            created_at=existing.created_at if existing else datetime.now(),
            use_count=existing.use_count if existing else 0,
            pattern=self.pattern_entry.get(),
            ledger_name=self.ledger_selector.get(),
            match_type=RuleMatchType(self.match_type.get()),
            voucher_type=VoucherType(self.voucher_type.get()),
            priority=priority,
            enabled=bool(self.enabled_switch.get()),
        )
        try:
            self.on_save(rule)
        except ValueError as exc:
            messagebox.showerror("Could not save rule", str(exc), parent=self)
            return
        self.clear_form()
        self.refresh()

    def _load_selected(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        rule = self.rules[selected[0]]
        self.selected_rule_id = rule.id
        self.pattern_entry.delete(0, "end")
        self.pattern_entry.insert(0, rule.pattern)
        self.match_type.set(rule.match_type.value)
        selected_ledger = rule.ledger_name or LEGACY_LEDGER_LABEL
        values = self.ledger_names or [selected_ledger]
        if selected_ledger not in values:
            values = [selected_ledger, *values]
            self.ledger_selector.configure(values=values)
        self.ledger_selector.set(selected_ledger)
        self.voucher_type.set(rule.voucher_type.value)
        self.priority_entry.delete(0, "end")
        self.priority_entry.insert(0, str(rule.priority))
        self.enabled_switch.select() if rule.enabled else self.enabled_switch.deselect()

    def _delete(self) -> None:
        selected = self.tree.selection()
        if selected and messagebox.askyesno("Delete rule", "Delete the selected matching rule?", parent=self):
            self.on_delete(selected[0])
            self.clear_form()
            self.refresh()
