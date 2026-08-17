"""Reusable compact controls for the unified accounting workspace."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from decimal import Decimal

import customtkinter as ctk
from PIL import Image

from app.models.enums import VoucherType
from app.utils.amounts import format_decimal
from app.utils.ledger_names import is_numeric_ledger_reference
from app.utils.runtime_paths import resource_path
from app.views.theme import INPUT_STYLE, button_style, color

DISABLED_TEXT = color("disabled_text")


def _set_button_enabled(button: ctk.CTkButton, enabled: bool, kind: str) -> None:
    """Apply both the functional state and an unambiguous static visual state."""

    visual = button_style(kind)
    if not enabled:
        visual.update(
            fg_color=color("disabled_background"),
            hover_color=color("disabled_background"),
            border_color=color("border"),
        )
    button.configure(state="normal" if enabled else "disabled", **visual)


class TopToolbar(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        on_test_tally: Callable[[], None],
        on_settings: Callable[[], None],
        on_toggle_details: Callable[[], None],
    ) -> None:
        super().__init__(master, corner_radius=0, height=52, fg_color=color("header"))
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)
        brand = ctk.CTkFrame(self, fg_color="transparent")
        brand.grid(row=0, column=0, padx=(14, 18), pady=7, sticky="w")
        with Image.open(resource_path("app/assets/jd_tool_logo.png")) as source:
            logo = source.convert("RGBA")
        self.logo_image = ctk.CTkImage(light_image=logo, dark_image=logo, size=(36, 36))
        ctk.CTkLabel(
            brand,
            text="",
            image=self.logo_image,
            width=36,
            height=36,
        ).pack(side="left")
        ctk.CTkLabel(
            brand,
            text="JD Tool",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=color("header_text"),
        ).pack(side="left", padx=(9, 0))
        self.connection = ctk.CTkLabel(
            self,
            text="●  Tally disconnected",
            text_color=color("danger"),
            font=ctk.CTkFont(size=12, weight="bold"),
        )
        self.connection.grid(row=0, column=2, padx=10, pady=10)
        self.tally_connect_button = ctk.CTkButton(
            self,
            text="Tally Connect",
            width=104,
            height=30,
            command=on_test_tally,
            **button_style("secondary"),
        )
        self.tally_connect_button.grid(row=0, column=3, padx=(2, 6), pady=10)
        ctk.CTkButton(
            self,
            text="Details",
            width=76,
            height=30,
            command=on_toggle_details,
            **button_style("secondary"),
        ).grid(row=0, column=4, padx=(2, 6), pady=10)
        ctk.CTkButton(
            self,
            text="Settings",
            width=82,
            height=30,
            command=on_settings,
            **button_style("primary"),
        ).grid(row=0, column=5, padx=(2, 14), pady=10)

    def set_connection(self, state: str, message: str = "") -> None:
        colors = {"connected": color("success"), "connecting": color("warning"), "disconnected": color("danger")}
        labels = {"connected": "Tally connected", "connecting": "Connecting…", "disconnected": "Tally disconnected"}
        self.connection.configure(
            text=f"●  {message or labels.get(state, state.title())}",
            text_color=colors.get(state, color("text_muted")),
        )

    def set_busy(self, busy: bool) -> None:
        self.tally_connect_button.configure(state="disabled" if busy else "normal")


class FileControlPanel(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        bank_choices: list[str],
        default_bank: str,
        on_browse: Callable[[], None],
        on_extract: Callable[[], None],
        on_refresh_ledgers: Callable[[str], None],
        on_match: Callable[[str], None],
    ) -> None:
        super().__init__(
            master, corner_radius=6, fg_color=color("surface"), border_width=1, border_color=color("separator")
        )
        for column in (0, 1, 2, 3):
            self.grid_columnconfigure(column, weight=1)

        self.file_path = ctk.CTkEntry(self, placeholder_text="Choose or drop a bank statement PDF", **INPUT_STYLE)
        self.file_path.grid(row=0, column=0, columnspan=2, padx=(10, 5), pady=(9, 5), sticky="ew")
        ctk.CTkButton(self, text="Browse", width=76, height=30, command=on_browse, **button_style("secondary")).grid(
            row=0, column=2, padx=5, pady=(9, 5), sticky="w"
        )
        self.extract_button = ctk.CTkButton(
            self,
            text="Extract Transactions",
            width=150,
            height=32,
            command=on_extract,
            **button_style("primary"),
        )
        self.extract_button.grid(row=0, column=3, padx=(5, 10), pady=(9, 5), sticky="e")

        self.bank = ctk.CTkComboBox(self, values=bank_choices, state="readonly", height=29, **INPUT_STYLE)
        self.bank.set(default_bank if default_bank in bank_choices else "Automatic")
        self.bank.grid(row=1, column=0, padx=(10, 5), pady=(5, 9), sticky="ew")
        self.password = ctk.CTkEntry(
            self, placeholder_text="PDF password (not saved)", show="•", height=29, **INPUT_STYLE
        )
        self.password.grid(row=1, column=1, padx=5, pady=(5, 9), sticky="ew")
        self.company = ctk.CTkComboBox(
            self, values=["Connect to Tally first"], state="readonly", height=29, **INPUT_STYLE
        )
        self.company.set("Connect to Tally first")
        self.company.grid(row=1, column=2, padx=5, pady=(5, 9), sticky="ew")
        tally_actions = ctk.CTkFrame(self, fg_color="transparent")
        tally_actions.grid(row=1, column=3, padx=(5, 10), pady=(5, 9), sticky="ew")
        tally_actions.grid_columnconfigure(0, weight=1)
        self.bank_ledger = ctk.CTkComboBox(
            tally_actions, values=["Refresh Tally ledgers"], state="readonly", height=29, **INPUT_STYLE
        )
        self.bank_ledger.set("Refresh Tally ledgers")
        self.bank_ledger.grid(row=0, column=0, padx=(0, 4), sticky="ew")
        self.match_button = ctk.CTkButton(
            tally_actions,
            text="Match",
            width=58,
            height=31,
            command=lambda: on_match(self.bank_ledger.get()),
            **button_style("primary"),
        )
        self.match_button.grid(row=0, column=1, padx=2)
        self.refresh_button = ctk.CTkButton(
            tally_actions,
            text="Refresh",
            width=56,
            height=31,
            command=lambda: on_refresh_ledgers(self.company.get()),
            **button_style("primary"),
        )
        self.refresh_button.grid(row=0, column=2, padx=2)

    def set_file(self, path: str) -> None:
        self.file_path.delete(0, "end")
        self.file_path.insert(0, path)

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for button in (self.extract_button, self.refresh_button, self.match_button):
            button.configure(state=state)

    def set_companies(self, companies: list[str], selected: str = "") -> None:
        choices = companies or ["No company is open"]
        self.company.configure(values=choices)
        self.company.set(selected if selected in choices else choices[0])

    def set_ledgers(self, ledgers: list[str], default: str = "") -> None:
        choices = [
            name.strip() for name in ledgers if name.strip() and not is_numeric_ledger_reference(name)
        ] or ["No bank or cash ledgers found"]
        self.bank_ledger.configure(values=choices)
        self.bank_ledger.set(default if default in choices else choices[0])


class SummaryBar(ctk.CTkFrame):
    KEYS = (
        ("transactions", "Transactions"),
        ("debit", "Total Debit"),
        ("credit", "Total Credit"),
        ("opening", "Opening"),
        ("closing", "Closing"),
        ("unmatched", "Unmatched"),
        ("errors", "Errors"),
        ("duplicates", "Duplicates"),
    )

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, corner_radius=6, fg_color=color("background"))
        self.values: dict[str, ctk.CTkLabel] = {}
        for index, (key, title) in enumerate(self.KEYS):
            self.grid_columnconfigure(index, weight=1)
            cell = ctk.CTkFrame(
                self,
                fg_color=color("surface"),
                border_width=1,
                border_color=color("separator"),
                corner_radius=5,
            )
            cell.grid(row=0, column=index, padx=5, pady=5, sticky="ew")
            ctk.CTkLabel(
                cell,
                text=title,
                font=ctk.CTkFont(size=12),
                text_color=color("text_secondary"),
            ).pack()
            value = ctk.CTkLabel(cell, text="0", font=ctk.CTkFont(size=15, weight="bold"))
            value.pack()
            self.values[key] = value

    def update_values(
        self,
        *,
        transactions: int,
        debit: Decimal,
        credit: Decimal,
        opening: Decimal | None,
        closing: Decimal | None,
        unmatched: int,
        errors: int,
        duplicates: int,
    ) -> None:
        data = {
            "transactions": f"{transactions:,}",
            "debit": f"₹{format_decimal(debit)}",
            "credit": f"₹{format_decimal(credit)}",
            "opening": "—" if opening is None else f"₹{format_decimal(opening)}",
            "closing": "—" if closing is None else f"₹{format_decimal(closing)}",
            "unmatched": f"{unmatched:,}",
            "errors": f"{errors:,}",
            "duplicates": f"{duplicates:,}",
        }
        for key, value in data.items():
            self.values[key].configure(text=value)
        self.values["debit"].configure(text_color=color("danger"))
        self.values["credit"].configure(text_color=color("success"))
        self.values["errors"].configure(text_color=color("danger") if errors else color("text_primary"))
        self.values["unmatched"].configure(text_color=color("warning") if unmatched else color("text_primary"))
        self.values["duplicates"].configure(text_color=color("warning") if duplicates else color("text_primary"))


class FilterToolbar(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        on_change: Callable[[], None],
        on_clear: Callable[[], None],
        on_undo: Callable[[], None],
        on_redo: Callable[[], None],
        on_previous: Callable[[], None],
        on_next: Callable[[], None],
    ) -> None:
        super().__init__(
            master, corner_radius=6, fg_color=color("surface"), border_width=1, border_color=color("separator")
        )
        self.on_change = on_change
        self.search = ctk.CTkEntry(self, placeholder_text="Search transactions…", width=200, height=32, **INPUT_STYLE)
        self.search.pack(side="left", padx=(8, 4), pady=6)
        self.search.bind("<KeyRelease>", lambda _event: on_change())
        self.direction = self._combo(["All", "Debit", "Credit"], "All", 70)
        self.voucher = self._combo(["All vouchers", *[item.value for item in VoucherType]], "All vouchers", 112)
        self.match = self._combo(["All matches", "Matched", "Unmatched"], "All matches", 106)
        self.validation = self._combo(["All validation", "Valid", "Warning", "Error"], "All validation", 112)
        self.duplicate = self._combo(["All duplicates", "Duplicates", "Unique"], "All duplicates", 112)
        self.date_start = ctk.CTkEntry(self, placeholder_text="From YYYY-MM-DD", width=123, height=32, **INPUT_STYLE)
        self.date_end = ctk.CTkEntry(self, placeholder_text="To YYYY-MM-DD", width=123, height=32, **INPUT_STYLE)
        for entry in (self.date_start, self.date_end):
            entry.pack(side="left", padx=3, pady=6)
            entry.bind("<Return>", lambda _event: on_change())
        ctk.CTkButton(self, text="Clear", width=50, height=32, command=on_clear, **button_style("secondary")).pack(
            side="left", padx=3
        )
        navigation = ctk.CTkFrame(self, fg_color="transparent")
        navigation.pack(side="right", padx=(4, 7), pady=5)
        ctk.CTkButton(navigation, text="Undo", width=46, height=32, command=on_undo, **button_style("secondary")).pack(
            side="left", padx=2
        )
        ctk.CTkButton(navigation, text="Redo", width=46, height=32, command=on_redo, **button_style("secondary")).pack(
            side="left", padx=(2, 7)
        )
        ctk.CTkButton(
            navigation, text="Prev", width=46, height=32, command=on_previous, **button_style("secondary")
        ).pack(side="left", padx=2)
        self.page_label = ctk.CTkLabel(navigation, text="1 / 1", width=48, font=ctk.CTkFont(size=13, weight="bold"))
        self.page_label.pack(side="left", padx=1)
        ctk.CTkButton(navigation, text="Next", width=46, height=32, command=on_next, **button_style("secondary")).pack(
            side="left", padx=2
        )

    def _combo(self, values: list[str], initial: str, width: int) -> ctk.CTkComboBox:
        combo = ctk.CTkComboBox(
            self,
            values=values,
            state="readonly",
            width=width,
            height=32,
            command=lambda _value: self.on_change(),
            **INPUT_STYLE,
        )
        combo.set(initial)
        combo.pack(side="left", padx=3, pady=6)
        return combo

    def clear(self) -> None:
        self.search.delete(0, "end")
        self.direction.set("All")
        self.voucher.set("All vouchers")
        self.match.set("All matches")
        self.validation.set("All validation")
        self.duplicate.set("All duplicates")
        self.date_start.delete(0, "end")
        self.date_end.delete(0, "end")

    def set_page(self, current: int, total: int) -> None:
        self.page_label.configure(text=f"{current} / {total}")


class BulkActionToolbar(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        on_assign_ledger: Callable[[str], None],
        on_voucher: Callable[[str], None],
        on_ignore: Callable[[], None],
        on_delete: Callable[[], None],
        on_mark_valid: Callable[[], None],
        on_export_selected: Callable[[], None],
    ) -> None:
        super().__init__(
            master,
            corner_radius=6,
            fg_color=color("surface_secondary"),
            border_width=1,
            border_color=color("separator"),
        )
        self.selected = ctk.CTkLabel(self, text="Selected: 0", font=ctk.CTkFont(size=13, weight="bold"))
        self.selected.pack(side="left", padx=(10, 8), pady=5)
        self.ledger = ctk.CTkComboBox(self, values=["Assign Ledger"], width=180, height=28, **INPUT_STYLE)
        self.ledger.set("Assign Ledger")
        self.ledger.pack(side="left", padx=3, pady=5)
        ctk.CTkButton(
            self,
            text="Apply",
            width=48,
            height=28,
            command=lambda: on_assign_ledger(self.ledger.get()),
            **button_style("primary"),
        ).pack(side="left", padx=2)
        self.voucher = ctk.CTkComboBox(
            self,
            values=[item.value for item in VoucherType],
            width=105,
            height=28,
            state="readonly",
            **INPUT_STYLE,
        )
        self.voucher.set(VoucherType.PAYMENT.value)
        self.voucher.pack(side="left", padx=(8, 3), pady=5)
        ctk.CTkButton(
            self,
            text="Change Type",
            width=82,
            height=28,
            command=lambda: on_voucher(self.voucher.get()),
            **button_style("primary"),
        ).pack(side="left", padx=2)
        for label, command in (
            ("Ignore", on_ignore),
            ("Delete", on_delete),
            ("Mark Valid", on_mark_valid),
            ("Export Selected", on_export_selected),
        ):
            ctk.CTkButton(
                self,
                text=label,
                height=30,
                width=92,
                command=command,
                **button_style("danger" if label == "Delete" else "secondary"),
            ).pack(side="left", padx=3)

    def set_selected(self, count: int) -> None:
        self.selected.configure(text=f"Selected: {count:,}")

    def set_ledgers(self, ledgers: list[str]) -> None:
        choices = [
            name.strip() for name in ledgers if name.strip() and not is_numeric_ledger_reference(name)
        ] or ["Assign Ledger"]
        self.ledger.configure(values=choices)
        if self.ledger.get() not in choices:
            self.ledger.set(choices[0])


class BottomActionBar(ctk.CTkFrame):
    def __init__(
        self,
        master: tk.Misc,
        on_validate: Callable[[], None],
        on_preview: Callable[[], None],
        on_export: Callable[[], None],
        on_import: Callable[[], None],
    ) -> None:
        super().__init__(
            master,
            corner_radius=6,
            fg_color=color("surface_secondary"),
            border_width=1,
            border_color=color("separator"),
        )
        self.validation = ctk.CTkLabel(self, text="No transactions loaded", font=ctk.CTkFont(size=13, weight="bold"))
        self.validation.pack(side="left", padx=12, pady=7)
        self.import_button = ctk.CTkButton(
            self,
            text="Send to Tally",
            width=112,
            height=33,
            command=on_import,
            **button_style("success"),
        )
        self.import_button.pack(side="right", padx=(4, 10), pady=7)
        self.export_button = ctk.CTkButton(
            self, text="Export XML", width=100, height=33, command=on_export, **button_style("primary")
        )
        self.export_button.pack(side="right", padx=4, pady=7)
        self.preview_button = ctk.CTkButton(
            self,
            text="Preview XML",
            width=100,
            height=33,
            command=on_preview,
            **button_style("secondary"),
        )
        self.preview_button.pack(side="right", padx=4, pady=7)
        self.validate_button = ctk.CTkButton(
            self,
            text="Validate All",
            width=100,
            height=33,
            command=on_validate,
            **button_style("secondary"),
        )
        self.validate_button.pack(side="right", padx=4, pady=7)
        self.set_action_states(preview_enabled=False, export_enabled=False, tally_enabled=False)

    def set_summary(self, valid: int, errors: int, unmatched: int) -> None:
        self.validation.configure(text=f"✓ {valid:,} Valid    ⚠ {errors:,} Errors    {unmatched:,} Unmatched")

    def set_action_states(self, *, preview_enabled: bool, export_enabled: bool, tally_enabled: bool) -> None:
        _set_button_enabled(self.preview_button, preview_enabled, "secondary")
        _set_button_enabled(self.export_button, export_enabled, "primary")
        _set_button_enabled(self.import_button, tally_enabled, "success")

    def set_busy(self, busy: bool) -> None:
        _set_button_enabled(self.validate_button, not busy, "secondary")


class StatusBar(ctk.CTkFrame):
    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, corner_radius=0, height=28, fg_color=color("separator"))
        self.grid_propagate(False)
        self.grid_columnconfigure(0, weight=1)
        self.message = ctk.CTkLabel(
            self,
            text="Ready",
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=color("text_secondary"),
        )
        self.message.grid(row=0, column=0, padx=10, sticky="ew")
        self.progress = ctk.CTkProgressBar(
            self,
            width=180,
            height=8,
            mode="determinate",
            progress_color=color("primary"),
            fg_color=color("border"),
        )
        self.progress.set(0)
        self.progress.grid(row=0, column=1, padx=10)

    def set(self, message: str, progress: float | None = None) -> None:
        suffix = f"  ·  {round(max(0, min(1, progress)) * 100):d}%" if progress is not None else ""
        self.message.configure(text=f"{message}{suffix}")
        if progress is not None:
            self.progress.set(max(0, min(1, progress)))
