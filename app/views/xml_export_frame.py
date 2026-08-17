"""Phase 4 XML validation, preview, export, and direct-import screen."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

from app.models.export import (
    ExportGrouping,
    ExportOptions,
    ExportValidationReport,
    ImportBatch,
    VoucherMode,
    XmlExportResult,
)


class XmlExportFrame(ctk.CTkFrame):
    """Collect export options and present validation/XML/import reports."""

    def __init__(
        self,
        master: tk.Misc,
        default_export_folder: Path,
        on_validate: Callable[[ExportOptions, bool], ExportValidationReport],
        on_preview: Callable[[ExportOptions, bool], None],
        on_export: Callable[[Path, ExportOptions, bool], None],
        on_import: Callable[[ExportOptions, bool], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.on_validate = on_validate
        self.on_preview = on_preview
        self.on_export = on_export
        self.on_import = on_import
        ctk.CTkLabel(self, text="Tally XML Export", font=ctk.CTkFont(size=29, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text="Validate balanced vouchers, inspect the exact XML, save files, or import directly into Tally Prime.",
            text_color=("#566170", "#a8b0bc"),
        ).pack(anchor="w", pady=(5, 14))

        options = ctk.CTkFrame(self)
        options.pack(fill="x")
        labels = ("Tally company", "Voucher mode", "File grouping", "Base filename")
        for column, label in enumerate(labels):
            ctk.CTkLabel(options, text=label, font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=column, padx=8, pady=(9, 3), sticky="w")
            options.grid_columnconfigure(column, weight=1)
        self.company = ctk.CTkComboBox(options, values=["Connect to Tally first"])
        self.company.set("Connect to Tally first")
        self.company.grid(row=1, column=0, padx=8, pady=(0, 8), sticky="ew")
        self.mode = ctk.CTkComboBox(options, values=[item.value for item in VoucherMode], state="readonly")
        self.mode.set(VoucherMode.DOUBLE_ENTRY.value)
        self.mode.grid(row=1, column=1, padx=8, pady=(0, 8), sticky="ew")
        self.grouping = ctk.CTkComboBox(options, values=[item.value for item in ExportGrouping], state="readonly")
        self.grouping.set(ExportGrouping.COMBINED.value)
        self.grouping.grid(row=1, column=2, padx=8, pady=(0, 8), sticky="ew")
        self.base_filename = ctk.CTkEntry(options)
        self.base_filename.insert(0, "tally_bank_vouchers")
        self.base_filename.grid(row=1, column=3, padx=8, pady=(0, 8), sticky="ew")

        ctk.CTkLabel(options, text="Period start", font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=0, padx=8, pady=(2, 3), sticky="w")
        ctk.CTkLabel(options, text="Period end", font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=1, padx=8, pady=(2, 3), sticky="w")
        ctk.CTkLabel(options, text="Output folder", font=ctk.CTkFont(size=12, weight="bold")).grid(row=2, column=2, padx=8, pady=(2, 3), sticky="w")
        self.period_start = ctk.CTkEntry(options, placeholder_text="YYYY-MM-DD (optional)")
        self.period_start.grid(row=3, column=0, padx=8, pady=(0, 10), sticky="ew")
        self.period_end = ctk.CTkEntry(options, placeholder_text="YYYY-MM-DD (optional)")
        self.period_end.grid(row=3, column=1, padx=8, pady=(0, 10), sticky="ew")
        folder_cell = ctk.CTkFrame(options, fg_color="transparent")
        folder_cell.grid(row=3, column=2, columnspan=2, padx=8, pady=(0, 10), sticky="ew")
        self.output_folder = ctk.CTkEntry(folder_cell)
        self.output_folder.insert(0, str(default_export_folder))
        self.output_folder.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(folder_cell, text="Browse", width=75, command=self._browse_folder).pack(side="left", padx=(6, 0))

        action_bar = ctk.CTkFrame(self, fg_color="transparent")
        action_bar.pack(fill="x", pady=9)
        self.failed_only = ctk.CTkSwitch(action_bar, text="Failed imports only")
        self.failed_only.pack(side="left")
        self.bank_allocations = ctk.CTkSwitch(action_bar, text="Include bank allocations")
        self.bank_allocations.select()
        self.bank_allocations.pack(side="left", padx=12)
        self.validate_button = ctk.CTkButton(action_bar, text="Validate", width=95, command=self._validate)
        self.validate_button.pack(side="right", padx=(6, 0))
        self.preview_button = ctk.CTkButton(action_bar, text="Generate Preview", width=140, command=self._preview)
        self.preview_button.pack(side="right", padx=(6, 0))
        self.export_button = ctk.CTkButton(action_bar, text="Export XML Files", width=130, command=self._export)
        self.export_button.pack(side="right", padx=(6, 0))
        self.import_button = ctk.CTkButton(action_bar, text="Import into Tally", width=130, fg_color="#2b7a4b", command=self._import)
        self.import_button.pack(side="right", padx=(6, 0))

        self.progress = ctk.CTkProgressBar(self)
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(0, 5))
        self.status = ctk.CTkLabel(self, text="Run validation before export or import.", anchor="w")
        self.status.pack(fill="x", pady=(0, 8))

        tabs = ctk.CTkTabview(self)
        tabs.pack(fill="both", expand=True)
        validation_tab = tabs.add("Validation Report")
        preview_tab = tabs.add("XML Preview")
        import_tab = tabs.add("Import Report")
        self.validation_tree = ttk.Treeview(validation_tab, columns=("row", "severity", "message"), show="headings")
        self.validation_tree.heading("row", text="Row")
        self.validation_tree.heading("severity", text="Severity")
        self.validation_tree.heading("message", text="Message")
        self.validation_tree.column("row", width=75)
        self.validation_tree.column("severity", width=100)
        self.validation_tree.column("message", width=700)
        self.validation_tree.pack(fill="both", expand=True, padx=8, pady=8)
        self.preview_text = ctk.CTkTextbox(preview_tab, wrap="none", font=("Consolas", 11))
        self.preview_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.import_report = ctk.CTkTextbox(import_tab, wrap="word")
        self.import_report.pack(fill="both", expand=True, padx=8, pady=8)
        self.import_report.insert("1.0", "No direct import has been run.")
        self.import_report.configure(state="disabled")

    def set_companies(self, companies: list[str], selected: str = "") -> None:
        choices = companies or [selected or "Connect to Tally first"]
        self.company.configure(values=choices)
        if selected:
            self.company.set(selected)
        elif self.company.get() not in choices:
            self.company.set(choices[0])

    def get_options(self) -> ExportOptions:
        company = self.company.get().strip()
        if not company or company == "Connect to Tally first":
            raise ValueError("Connect to Tally and select a company, or enter its exact name.")
        start = self._parse_optional_date(self.period_start.get(), "period start")
        end = self._parse_optional_date(self.period_end.get(), "period end")
        if start and end and start > end:
            raise ValueError("Period start cannot be after period end.")
        return ExportOptions(
            company_name=company,
            voucher_mode=VoucherMode(self.mode.get()),
            grouping=ExportGrouping(self.grouping.get()),
            period_start=start,
            period_end=end,
            include_bank_allocations=bool(self.bank_allocations.get()),
            base_filename=self.base_filename.get().strip() or "tally_bank_vouchers",
        )

    def show_validation(self, report: ExportValidationReport) -> None:
        self.validation_tree.delete(*self.validation_tree.get_children())
        for issue in report.issues:
            self.validation_tree.insert("", "end", values=(issue.row_number, issue.severity, issue.message))
        errors = len(report.invalid_transaction_ids)
        warnings = sum(issue.severity == "Warning" for issue in report.issues)
        self.status.configure(
            text=f"Valid vouchers: {len(report.valid_transaction_ids):,} • Invalid: {errors:,} • Warnings: {warnings:,}"
        )

    def show_preview(self, xml_text: str, report: ExportValidationReport) -> None:
        self.show_validation(report)
        self.preview_text.delete("1.0", "end")
        self.preview_text.insert("1.0", xml_text)
        self.status.configure(text=f"Preview generated for {len(report.valid_transaction_ids):,} voucher(s).")

    def show_export_result(self, result: XmlExportResult) -> None:
        self.show_validation(result.validation)
        paths = "\n".join(str(path) for path in result.files)
        self.status.configure(text=f"Exported {len(result.exported_transaction_ids):,} vouchers to {len(result.files)} XML file(s).")
        messagebox.showinfo("XML export complete", f"Saved:\n{paths}", parent=self)

    def show_import_batch(self, batch: ImportBatch) -> None:
        report = (
            f"Company: {batch.company_name}\n"
            f"Requested vouchers: {batch.total_vouchers}\n"
            f"Created: {batch.created}\nAltered: {batch.altered}\nIgnored: {batch.ignored}\n"
            f"Errors reported by Tally: {batch.errors}\nFailed transactions: {batch.failed}\n\n"
            + ("Messages:\n" + "\n".join(batch.messages) if batch.messages else "No Tally error messages.")
        )
        self.import_report.configure(state="normal")
        self.import_report.delete("1.0", "end")
        self.import_report.insert("1.0", report)
        self.import_report.configure(state="disabled")
        self.status.configure(text=f"Import complete: {batch.created} created, {batch.altered} altered, {batch.failed} failed.")

    def set_busy(self, busy: bool, message: str = "") -> None:
        state = "disabled" if busy else "normal"
        for button in (self.validate_button, self.preview_button, self.export_button, self.import_button):
            button.configure(state=state)
        if not busy:
            self.progress.set(0)
        if message:
            self.status.configure(text=message)

    def set_progress(self, current: int, total: int, message: str) -> None:
        self.progress.set(current / total if total else 0)
        self.status.configure(text=f"Importing {current}/{total}: {message}")

    def _validate(self) -> None:
        try:
            self.show_validation(self.on_validate(self.get_options(), bool(self.failed_only.get())))
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Validation failed", str(exc), parent=self)

    def _preview(self) -> None:
        try:
            self.on_preview(self.get_options(), bool(self.failed_only.get()))
        except ValueError as exc:
            messagebox.showerror("Invalid export options", str(exc), parent=self)

    def _export(self) -> None:
        try:
            self.on_export(Path(self.output_folder.get()), self.get_options(), bool(self.failed_only.get()))
        except ValueError as exc:
            messagebox.showerror("Invalid export options", str(exc), parent=self)

    def _import(self) -> None:
        try:
            self.on_import(self.get_options(), bool(self.failed_only.get()))
        except ValueError as exc:
            messagebox.showerror("Invalid import options", str(exc), parent=self)

    def _browse_folder(self) -> None:
        selected = filedialog.askdirectory(parent=self, title="Select XML export folder", initialdir=self.output_folder.get())
        if selected:
            self.output_folder.delete(0, "end")
            self.output_folder.insert(0, selected)

    @staticmethod
    def _parse_optional_date(value: str, label: str) -> date | None:
        if not value.strip():
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"{label.title()} must use YYYY-MM-DD.") from exc
