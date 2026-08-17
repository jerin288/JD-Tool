"""Manual column mapping and source preview screen."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import customtkinter as ctk

from app.models.mapping import ColumnMapping

FIELD_LABELS = {
    "transaction_date": "Transaction date *",
    "value_date": "Value date",
    "description": "Description *",
    "reference_number": "Reference number",
    "cheque_number": "Cheque number",
    "debit": "Debit / withdrawal",
    "credit": "Credit / deposit",
    "amount": "Single amount",
    "dr_cr": "DR / CR indicator",
    "balance": "Balance",
}


class MappingFrame(ctk.CTkFrame):
    """Shows raw extracted rows and lets users correct automatic field mappings."""

    def __init__(
        self,
        master: tk.Misc,
        on_continue: Callable[[ColumnMapping], None],
        on_save_template: Callable[[ColumnMapping], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.on_continue = on_continue
        self.on_save_template = on_save_template
        self.rows: list[list[str]] = []
        self.mapping = ColumnMapping()
        self.selectors: dict[str, ctk.CTkComboBox] = {}
        self.option_to_index: dict[str, int | None] = {"Not mapped": None}

        ctk.CTkLabel(self, text="Column Mapping", font=ctk.CTkFont(size=26, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Confirm the automatically detected columns. Required fields are marked with an asterisk.",
            text_color=("#4b5563", "#aeb5bf"),
        ).pack(anchor="w", pady=(4, 16))
        mapping_panel = ctk.CTkFrame(self)
        mapping_panel.pack(fill="x", pady=(0, 12))
        for index, (field_name, label) in enumerate(FIELD_LABELS.items()):
            row, column = divmod(index, 5)
            cell = ctk.CTkFrame(mapping_panel, fg_color="transparent")
            cell.grid(row=row * 2, column=column, padx=10, pady=(10, 2), sticky="ew")
            ctk.CTkLabel(cell, text=label, font=ctk.CTkFont(size=12, weight="bold")).pack(anchor="w")
            selector = ctk.CTkComboBox(mapping_panel, values=["Not mapped"], state="readonly", width=220)
            selector.grid(row=row * 2 + 1, column=column, padx=10, pady=(0, 10), sticky="ew")
            self.selectors[field_name] = selector
            mapping_panel.grid_columnconfigure(column, weight=1)

        options_row = ctk.CTkFrame(self, fg_color="transparent")
        options_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(options_row, text="Header row").pack(side="left")
        self.header_row = ctk.CTkEntry(options_row, width=70)
        self.header_row.pack(side="left", padx=(8, 20))
        ctk.CTkLabel(options_row, text="Date format").pack(side="left")
        self.date_format = ctk.CTkComboBox(
            options_row,
            values=["AUTO", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y", "%Y-%m-%d"],
            width=150,
        )
        self.date_format.pack(side="left", padx=8)
        ctk.CTkButton(options_row, text="Create Review Table", command=self._continue, width=180).pack(side="right")
        if self.on_save_template:
            ctk.CTkButton(
                options_row, text="Save as Bank Template", command=self._save_template,
                width=180, fg_color="transparent", border_width=1,
            ).pack(side="right", padx=8)

        preview_panel = ctk.CTkFrame(self)
        preview_panel.pack(fill="both", expand=True)
        ctk.CTkLabel(preview_panel, text="Extracted data preview", font=ctk.CTkFont(size=15, weight="bold")).pack(anchor="w", padx=12, pady=10)
        self.preview_container = ttk.Frame(preview_panel)
        self.preview_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.preview: ttk.Treeview | None = None

    def load(self, rows: list[list[str]], mapping: ColumnMapping) -> None:
        self.rows = rows
        self.mapping = mapping
        width = max((len(row) for row in rows), default=0)
        options = ["Not mapped"]
        self.option_to_index = {"Not mapped": None}
        header = rows[mapping.header_row] if rows and mapping.header_row < len(rows) else []
        for index in range(width):
            sample = header[index].strip() if index < len(header) else ""
            label = f"Column {self._column_name(index)} — {sample[:28] or '(blank)'}"
            options.append(label)
            self.option_to_index[label] = index
        for field_name, selector in self.selectors.items():
            selector.configure(values=options)
            selected_index = getattr(mapping, field_name)
            selector.set(next((label for label, index in self.option_to_index.items() if index == selected_index), "Not mapped"))
        self.header_row.delete(0, "end")
        self.header_row.insert(0, str(mapping.header_row + 1))
        self.date_format.set(mapping.date_format)
        self._render_preview(width)

    def _render_preview(self, width: int) -> None:
        if self.preview:
            self.preview.destroy()
        columns = [f"c{index}" for index in range(width)]
        self.preview = ttk.Treeview(self.preview_container, columns=columns, show="headings", height=15)
        horizontal = ttk.Scrollbar(self.preview_container, orient="horizontal", command=self.preview.xview)
        vertical = ttk.Scrollbar(self.preview_container, orient="vertical", command=self.preview.yview)
        self.preview.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        for index, column in enumerate(columns):
            self.preview.heading(column, text=f"{self._column_name(index)}")
            self.preview.column(column, width=160, minwidth=80)
        for row_index, row in enumerate(self.rows[:250], start=1):
            self.preview.insert("", "end", values=row, text=str(row_index))
        self.preview.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.preview_container.rowconfigure(0, weight=1)
        self.preview_container.columnconfigure(0, weight=1)

    def _continue(self) -> None:
        self.on_continue(self.get_mapping())

    def _save_template(self) -> None:
        if self.on_save_template:
            self.on_save_template(self.get_mapping())

    def get_mapping(self) -> ColumnMapping:
        try:
            header_row = max(0, int(self.header_row.get()) - 1)
        except ValueError:
            header_row = 0
        values = {
            field_name: self.option_to_index.get(selector.get())
            for field_name, selector in self.selectors.items()
        }
        return ColumnMapping(**values, header_row=header_row, date_format=self.date_format.get())

    @staticmethod
    def _column_name(index: int) -> str:
        name = ""
        value = index + 1
        while value:
            value, remainder = divmod(value - 1, 26)
            name = chr(65 + remainder) + name
        return name
