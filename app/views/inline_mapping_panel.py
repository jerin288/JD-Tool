"""Collapsible in-workspace column mapping controls."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from app.models.mapping import ColumnMapping
from app.views.theme import INPUT_STYLE, button_style, color

FIELDS = (
    ("transaction_date", "Transaction Date *"),
    ("value_date", "Value Date"),
    ("description", "Description *"),
    ("reference_number", "Reference"),
    ("cheque_number", "Cheque No."),
    ("debit", "Debit / Withdrawal"),
    ("credit", "Credit / Deposit"),
    ("amount", "Single Amount"),
    ("dr_cr", "DR / CR"),
    ("balance", "Balance"),
)


class InlineMappingPanel(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        on_apply: Callable[[ColumnMapping], None],
        on_save_template: Callable[[ColumnMapping], None],
    ) -> None:
        super().__init__(
            master, corner_radius=6, fg_color=color("surface"), border_width=1, border_color=color("separator")
        )
        self.on_apply = on_apply
        self.on_save_template = on_save_template
        self.rows: list[list[str]] = []
        self.mapping = ColumnMapping()
        self.option_to_index: dict[str, int | None] = {"Not mapped": None}
        self.selectors: dict[str, ctk.CTkComboBox] = {}
        self.expanded = True

        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(header, text="Column Mapping", font=ctk.CTkFont(size=13, weight="bold")).pack(side="left")
        self.hint = ctk.CTkLabel(header, text="Confirm required fields before review", text_color=color("text_muted"))
        self.hint.pack(side="left", padx=12)
        self.toggle_button = ctk.CTkButton(
            header, text="Collapse ▲", width=82, height=25, command=self.toggle, **button_style("secondary")
        )
        self.toggle_button.pack(side="right")

        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="x", padx=6, pady=(0, 7))
        for column in range(5):
            self.body.grid_columnconfigure(column, weight=1)
        for index, (field_name, label) in enumerate(FIELDS):
            row, column = divmod(index, 5)
            cell = ctk.CTkFrame(self.body, fg_color="transparent")
            cell.grid(row=row, column=column, padx=4, pady=2, sticky="ew")
            ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(size=10, weight="bold")).pack(anchor="w")
            selector = ctk.CTkComboBox(cell, values=["Not mapped"], state="readonly", height=27, **INPUT_STYLE)
            selector.pack(fill="x")
            self.selectors[field_name] = selector

        options = ctk.CTkFrame(self.body, fg_color="transparent")
        options.grid(row=2, column=0, columnspan=5, sticky="ew", padx=4, pady=(5, 0))
        ctk.CTkLabel(options, text="Header row").pack(side="left")
        self.header_row = ctk.CTkEntry(options, width=56, height=27, **INPUT_STYLE)
        self.header_row.pack(side="left", padx=(5, 12))
        ctk.CTkLabel(options, text="Date format").pack(side="left")
        self.date_format = ctk.CTkComboBox(
            options,
            values=["AUTO", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d"],
            width=130,
            height=27,
            **INPUT_STYLE,
        )
        self.date_format.pack(side="left", padx=5)
        ctk.CTkButton(
            options,
            text="Apply Mapping",
            width=105,
            height=28,
            command=lambda: self.on_apply(self.get_mapping()),
            **button_style("primary"),
        ).pack(side="right")
        ctk.CTkButton(
            options,
            text="Save as Bank Template",
            width=145,
            height=28,
            command=lambda: self.on_save_template(self.get_mapping()),
            **button_style("secondary"),
        ).pack(side="right", padx=6)

    def load(self, rows: list[list[str]], mapping: ColumnMapping) -> None:
        self.rows = rows
        self.mapping = mapping
        width = max((len(row) for row in rows), default=0)
        header = rows[mapping.header_row] if rows and mapping.header_row < len(rows) else []
        options = ["Not mapped"]
        self.option_to_index = {"Not mapped": None}
        for index in range(width):
            sample = header[index].strip() if index < len(header) else ""
            label = f"{self._column_name(index)} — {sample[:24] or '(blank)'}"
            options.append(label)
            self.option_to_index[label] = index
        for field_name, selector in self.selectors.items():
            selector.configure(values=options)
            selected_index = getattr(mapping, field_name)
            selector.set(
                next((label for label, value in self.option_to_index.items() if value == selected_index), "Not mapped")
            )
        self.header_row.delete(0, "end")
        self.header_row.insert(0, str(mapping.header_row + 1))
        self.date_format.set(mapping.date_format)
        self.hint.configure(text=f"{len(rows):,} extracted rows • {width} source columns")

    def get_mapping(self) -> ColumnMapping:
        try:
            header_row = max(0, int(self.header_row.get()) - 1)
        except ValueError:
            header_row = 0
        values = {
            field_name: self.option_to_index.get(selector.get()) for field_name, selector in self.selectors.items()
        }
        return ColumnMapping(**values, header_row=header_row, date_format=self.date_format.get())

    def toggle(self) -> None:
        self.set_expanded(not self.expanded)

    def set_expanded(self, expanded: bool) -> None:
        self.expanded = expanded
        if expanded:
            self.body.pack(fill="x", padx=6, pady=(0, 7))
            self.toggle_button.configure(text="Collapse ▲")
        else:
            self.body.pack_forget()
            self.toggle_button.configure(text="Expand ▼")

    @staticmethod
    def _column_name(index: int) -> str:
        name = ""
        value = index + 1
        while value:
            value, remainder = divmod(value - 1, 26)
            name = chr(65 + remainder) + name
        return name
