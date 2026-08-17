"""In-window settings drawer and advanced export options."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import customtkinter as ctk

from app import __version__
from app.models.export import ExportGrouping, ExportOptions, VoucherMode
from app.views.theme import INPUT_STYLE, button_style, color


class ExportSettingsPanel(ctk.CTkFrame):
    def __init__(self, master: tk.Misc, default_folder: Path) -> None:
        super().__init__(master, fg_color="transparent")
        self.mode = self._row("Voucher mode", [item.value for item in VoucherMode], VoucherMode.DOUBLE_ENTRY.value)
        self.grouping = self._row(
            "File grouping", [item.value for item in ExportGrouping], ExportGrouping.COMBINED.value
        )
        ctk.CTkLabel(self, text="Base filename", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=8, pady=(8, 2))
        self.base_filename = ctk.CTkEntry(self, **INPUT_STYLE)
        self.base_filename.insert(0, "tally_bank_vouchers")
        self.base_filename.pack(fill="x", padx=8)
        dates = ctk.CTkFrame(self, fg_color="transparent")
        dates.pack(fill="x", padx=5, pady=7)
        dates.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(dates, text="Period start", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, padx=3, sticky="w"
        )
        ctk.CTkLabel(dates, text="Period end", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=1, padx=3, sticky="w"
        )
        self.period_start = ctk.CTkEntry(dates, placeholder_text="YYYY-MM-DD", **INPUT_STYLE)
        self.period_start.grid(row=1, column=0, padx=3, sticky="ew")
        self.period_end = ctk.CTkEntry(dates, placeholder_text="YYYY-MM-DD", **INPUT_STYLE)
        self.period_end.grid(row=1, column=1, padx=3, sticky="ew")
        ctk.CTkLabel(self, text="Output folder", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=8, pady=(5, 2))
        self.output_folder = ctk.CTkEntry(self, **INPUT_STYLE)
        self.output_folder.insert(0, str(default_folder))
        self.output_folder.pack(fill="x", padx=8)
        self.bank_allocations = ctk.CTkSwitch(self, text="Include bank allocations")
        self.bank_allocations.select()
        self.bank_allocations.pack(anchor="w", padx=8, pady=(10, 2))
        self.failed_only = ctk.CTkSwitch(self, text="Retry failed imports only")
        self.failed_only.pack(anchor="w", padx=8, pady=2)
        ctk.CTkLabel(
            self,
            text=(
                "The company is taken from the main workspace. "
                "Export and import remain disabled until validation passes."
            ),
            wraplength=430,
            justify="left",
            text_color=color("text_muted"),
        ).pack(anchor="w", padx=8, pady=12)

    def _row(self, label: str, values: list[str], initial: str) -> ctk.CTkComboBox:
        ctk.CTkLabel(self, text=label, font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=8, pady=(8, 2))
        combo = ctk.CTkComboBox(self, values=values, state="readonly", **INPUT_STYLE)
        combo.set(initial)
        combo.pack(fill="x", padx=8)
        return combo

    def get_options(self, company_name: str) -> ExportOptions:
        company = company_name.strip()
        if not company or company in {"Connect to Tally first", "No company is open"}:
            raise ValueError("Connect to Tally and select the target company first.")
        start = self._parse_date(self.period_start.get(), "Period start")
        end = self._parse_date(self.period_end.get(), "Period end")
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

    def output_path(self) -> Path:
        return Path(self.output_folder.get().strip() or "exports")

    @staticmethod
    def _parse_date(value: str, label: str) -> date | None:
        if not value.strip():
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"{label} must use YYYY-MM-DD.") from exc


class SettingsDrawer(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        default_folder: Path,
        appearance_mode: str,
        server_url: str,
        app_settings: dict[str, object],
        on_check_updates: Callable[[], None],
        on_close: Callable[[], None],
        on_theme: Callable[[str], None],
        on_save_settings: Callable[[dict[str, object]], None],
        on_export_excel: Callable[[], None],
        on_show_mapping: Callable[[], None],
        on_backup: Callable[[], None],
        on_open_logs: Callable[[], None],
    ) -> None:
        super().__init__(
            master,
            width=590,
            corner_radius=0,
            fg_color=color("surface"),
            border_width=1,
            border_color=color("border"),
        )
        self.grid_propagate(False)
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 0))
        ctk.CTkLabel(header, text="Settings & Tools", font=ctk.CTkFont(size=17, weight="bold")).pack(side="left")
        ctk.CTkButton(header, text="Close ×", width=70, height=28, command=on_close, **button_style("secondary")).pack(
            side="right"
        )
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=8, pady=8)
        self.export_tab = self.tabs.add("Export")
        self.templates_tab = self.tabs.add("Templates")
        self.rules_tab = self.tabs.add("Rules")
        self.history_tab = self.tabs.add("History")
        self.app_tab = self.tabs.add("App")
        self.export_settings = ExportSettingsPanel(self.export_tab, default_folder)
        self.export_settings.pack(fill="both", expand=True)

        ctk.CTkLabel(self.app_tab, text="Appearance", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=8, pady=(10, 2)
        )
        theme = ctk.CTkComboBox(
            self.app_tab,
            values=["System", "Light", "Dark"],
            state="readonly",
            command=on_theme,
            **INPUT_STYLE,
        )
        theme.set(appearance_mode)
        theme.pack(fill="x", padx=8)
        ctk.CTkLabel(self.app_tab, text="Tally server URL", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=8, pady=(10, 2)
        )
        self.server_url = ctk.CTkEntry(self.app_tab, **INPUT_STYLE)
        self.server_url.insert(0, server_url)
        self.server_url.pack(fill="x", padx=8)
        ctk.CTkLabel(self.app_tab, text="Default export folder", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=8, pady=(10, 2)
        )
        self.default_folder = ctk.CTkEntry(self.app_tab, **INPUT_STYLE)
        self.default_folder.insert(0, str(default_folder))
        self.default_folder.pack(fill="x", padx=8)
        advanced = ctk.CTkFrame(self.app_tab, fg_color="transparent")
        advanced.pack(fill="x", padx=8, pady=(8, 0))
        advanced.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(advanced, text="Tesseract executable", font=ctk.CTkFont(weight="bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        self.ocr_path = ctk.CTkEntry(
            advanced, placeholder_text=r"C:\Program Files\Tesseract-OCR\tesseract.exe", **INPUT_STYLE
        )
        self.ocr_path.insert(0, str(app_settings.get("ocr_executable_path", "")))
        self.ocr_path.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 6))
        ctk.CTkLabel(advanced, text="OCR language", font=ctk.CTkFont(weight="bold")).grid(row=2, column=0, sticky="w")
        ctk.CTkLabel(advanced, text="OCR DPI", font=ctk.CTkFont(weight="bold")).grid(row=2, column=1, sticky="w")
        self.ocr_language = ctk.CTkEntry(advanced, **INPUT_STYLE)
        self.ocr_language.insert(0, str(app_settings.get("ocr_language", "eng")))
        self.ocr_language.grid(row=3, column=0, sticky="ew", padx=(0, 4))
        self.ocr_dpi = ctk.CTkComboBox(advanced, values=["200", "300", "400"], state="readonly", **INPUT_STYLE)
        self.ocr_dpi.set(str(app_settings.get("ocr_dpi", 300)))
        self.ocr_dpi.grid(row=3, column=1, sticky="ew", padx=(4, 0))
        ctk.CTkLabel(advanced, text="Logging level", font=ctk.CTkFont(weight="bold")).grid(
            row=4, column=0, sticky="w", pady=(7, 0)
        )
        self.logging_level = ctk.CTkComboBox(
            advanced, values=["DEBUG", "INFO", "WARNING", "ERROR"], state="readonly", **INPUT_STYLE
        )
        self.logging_level.set(str(app_settings.get("logging_level", "INFO")))
        self.logging_level.grid(row=5, column=0, sticky="ew", padx=(0, 4))
        self.automatic_backup = ctk.CTkSwitch(advanced, text="Daily automatic backup")
        if bool(app_settings.get("automatic_backup", False)):
            self.automatic_backup.select()
        self.automatic_backup.grid(row=5, column=1, sticky="w", padx=(4, 0))

        updates = ctk.CTkFrame(self.app_tab, fg_color=color("background"), corner_radius=6)
        updates.pack(fill="x", padx=8, pady=(10, 2))
        ctk.CTkLabel(
            updates,
            text=f"Updates  •  Current version v{__version__}",
            font=ctk.CTkFont(weight="bold"),
        ).pack(anchor="w", padx=10, pady=(9, 4))
        self.automatic_updates = ctk.CTkSwitch(updates, text="Automatically check for updates")
        if bool(app_settings.get("automatic_update_checks", True)):
            self.automatic_updates.select()
        self.automatic_updates.pack(anchor="w", padx=10, pady=3)
        self.update_status = ctk.CTkLabel(
            updates,
            text="Stable updates are checked through GitHub Releases.",
            wraplength=450,
            justify="left",
            anchor="w",
            text_color=color("text_muted"),
        )
        self.update_status.pack(fill="x", padx=10, pady=3)
        self.check_updates_button = ctk.CTkButton(
            updates,
            text="Check for Updates",
            height=30,
            command=on_check_updates,
            **button_style("secondary"),
        )
        self.check_updates_button.pack(fill="x", padx=10, pady=(4, 10))
        ctk.CTkButton(
            self.app_tab,
            text="Save Application Settings",
            height=30,
            command=lambda: on_save_settings(self.values()),
            **button_style("primary"),
        ).pack(fill="x", padx=8, pady=10)
        ctk.CTkButton(
            self.app_tab,
            text="Show Column Mapping",
            height=30,
            command=on_show_mapping,
            **button_style("secondary"),
        ).pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(
            self.app_tab,
            text="Export Transactions to Excel",
            height=30,
            command=on_export_excel,
            **button_style("secondary"),
        ).pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(
            self.app_tab,
            text="Back Up Application Data",
            height=30,
            command=on_backup,
            **button_style("secondary"),
        ).pack(fill="x", padx=8, pady=4)
        ctk.CTkButton(
            self.app_tab,
            text="Open Logs Folder",
            height=30,
            command=on_open_logs,
            **button_style("secondary"),
        ).pack(fill="x", padx=8, pady=4)
        ctk.CTkLabel(
            self.app_tab,
            text="OCR runs locally only when a page has no selectable text. Restart after changing logging level.",
            wraplength=470,
            justify="left",
            text_color=color("text_muted"),
        ).pack(anchor="w", padx=8, pady=14)

    def show_tab(self, name: str) -> None:
        self.tabs.set(name)

    def values(self) -> dict[str, object]:
        return {
            "tally_server_url": self.server_url.get().strip(),
            "default_export_folder": self.default_folder.get().strip(),
            "ocr_executable_path": self.ocr_path.get().strip(),
            "ocr_language": self.ocr_language.get().strip() or "eng",
            "ocr_dpi": int(self.ocr_dpi.get()),
            "logging_level": self.logging_level.get(),
            "automatic_backup": bool(self.automatic_backup.get()),
            "automatic_update_checks": bool(self.automatic_updates.get()),
        }

    def set_update_status(self, message: str, *, checking: bool = False) -> None:
        self.update_status.configure(text=message)
        self.check_updates_button.configure(state="disabled" if checking else "normal")

    def set_operation_busy(self, busy: bool) -> None:
        self.check_updates_button.configure(state="disabled" if busy else "normal")
