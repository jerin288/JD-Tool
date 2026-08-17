"""Unified single-window accounting workspace."""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import tkinter as tk
import webbrowser
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import customtkinter as ctk

from app.controllers.app_controller import AppController
from app.models.enums import DuplicateStatus, RuleMatchType, VoucherType
from app.models.export import ExportOptions
from app.models.mapping import ColumnMapping
from app.models.matching_rule import MatchingRule
from app.models.transaction import Transaction
from app.models.update import PreparedUpdate, UpdateRelease
from app.services.backup_service import BackupService
from app.services.ocr_service import OcrConfiguration
from app.services.pdf_extractor import IncorrectPdfPasswordError, PdfPasswordRequiredError
from app.services.settings_service import SettingsService
from app.services.update_service import (
    UpdateError,
    UpdateNetworkError,
    UpdateNotSupportedError,
    UpdateService,
    format_utc,
    utc_now,
)
from app.utils.runtime_paths import resource_path, tcl_path
from app.views.editable_table import EditableTransactionTable
from app.views.import_history_frame import ImportHistoryFrame
from app.views.inline_mapping_panel import InlineMappingPanel
from app.views.saved_rules_frame import SavedRulesFrame
from app.views.template_manager_frame import TemplateManagerFrame
from app.views.theme import COLORS, DARK_COLORS, button_style, color
from app.views.transaction_detail_panel import TransactionDetailPanel
from app.views.update_dialog import UpdateDialog
from app.views.workspace_components import (
    BottomActionBar,
    BulkActionToolbar,
    FileControlPanel,
    FilterToolbar,
    StatusBar,
    SummaryBar,
    TopToolbar,
)
from app.views.workspace_settings import SettingsDrawer

LOGGER = logging.getLogger(__name__)
BANKS = [
    "Automatic",
    "State Bank of India",
    "South Indian Bank",
    "Federal Bank",
    "HDFC Bank",
    "ICICI Bank",
    "Axis Bank",
    "Kotak Mahindra Bank",
    "Canara Bank",
    "Punjab National Bank",
    "Bank of Baroda",
    "Union Bank of India",
    "Yes Bank",
    "Other / Generic",
]


@dataclass(frozen=True, slots=True)
class ActionButtonStates:
    preview_enabled: bool
    export_enabled: bool
    tally_enabled: bool


def calculate_action_button_states(
    transaction_count: int,
    critical_error_count: int,
    tally_connected: bool,
    bank_ledger_selected: bool,
    *,
    busy: bool = False,
) -> ActionButtonStates:
    """Return the single source of truth for the three XML action buttons."""

    has_transactions = transaction_count > 0
    technically_valid = critical_error_count == 0
    return ActionButtonStates(
        preview_enabled=has_transactions and not busy,
        export_enabled=has_transactions and technically_valid and not busy,
        tally_enabled=(
            has_transactions and technically_valid and tally_connected and bank_ledger_selected and not busy
        ),
    )


def _create_root() -> ctk.CTk:
    try:
        from tkinterdnd2 import TkinterDnD

        class DragDropCTk(ctk.CTk, TkinterDnD.DnDWrapper):
            def __init__(self) -> None:
                ctk.CTk.__init__(self)
                try:
                    self.TkdndVersion = TkinterDnD._require(self)
                except Exception:
                    LOGGER.warning(
                        "Drag-and-drop is unavailable; file selection remains enabled",
                        exc_info=True,
                    )

        return DragDropCTk()
    except Exception:
        LOGGER.warning("Drag-and-drop is unavailable; file selection remains enabled")
        return ctk.CTk()


class BankStatementApplication:
    """One complete accounting workspace backed by the existing controller layer."""

    def __init__(
        self,
        controller: AppController,
        settings: SettingsService,
        project_root: Path,
        *,
        update_service: UpdateService | None = None,
    ) -> None:
        self.controller = controller
        self.settings = settings
        self.project_root = project_root
        self.update_service = update_service or UpdateService(project_root)
        self.available_update: UpdateRelease | None = None
        self.update_check_in_progress = False
        self.controller.state.tally_server_url = settings.get("tally_server_url", "http://localhost:9000")
        self.root = _create_root()
        self.window_icon = tk.PhotoImage(
            master=self.root,
            file=tcl_path(resource_path("app/assets/jd_tool_logo.png")),
        )
        self.root.iconphoto(True, self.window_icon)
        self.selected_pdf: Path | None = None
        self.busy = False
        self.tally_connected = False
        self.drawer_visible = False
        self.details_visible = False
        self.worker_events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.frames: dict[str, ctk.CTkFrame] = {}

        ctk.set_appearance_mode(settings.get("appearance_mode", "Light"))
        ctk.set_default_color_theme("blue")
        window = settings.get("window", {})
        self.root.title("JD Tool")
        self.root.geometry(f"{window.get('width', 1440)}x{window.get('height', 900)}")
        self.root.minsize(1120, 680)
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._configure_style()
        self._build_shell()
        self._bind_shortcuts()
        self.controller.on_state_changed = lambda: self.worker_events.put(("state_changed", None))
        self.root.after(80, self._poll_worker_events)
        self._start_automatic_backup()
        self.root.after(1500, self._start_automatic_update_check)
        self.root.after(1800, self._show_update_result)
        self._refresh_summary()

    def run(self) -> None:
        self.root.mainloop()

    def _configure_style(self) -> None:
        palette = DARK_COLORS if ctk.get_appearance_mode() == "Dark" else COLORS
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            rowheight=31,
            font=("Segoe UI", 10),
            borderwidth=1,
            relief="flat",
            background=palette["surface"],
            foreground=palette["text_primary"],
            fieldbackground=palette["surface"],
            bordercolor=palette["separator"],
        )
        style.configure(
            "Treeview.Heading",
            font=("Segoe UI", 10, "bold"),
            padding=(8, 7),
            background=palette["table_header"],
            foreground=palette["table_header_text"],
            bordercolor=palette["border"],
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", palette["table_selected"])],
            foreground=[("selected", palette["table_selected_text"])],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", palette["table_header"])],
            foreground=[("active", palette["table_header_text"])],
        )
        style.configure(
            "TEntry",
            fieldbackground=palette["surface"],
            foreground=palette["text_primary"],
            bordercolor=palette["border"],
        )
        style.configure(
            "TCombobox",
            fieldbackground=palette["surface"],
            foreground=palette["text_primary"],
            bordercolor=palette["border"],
        )

    def _build_shell(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(1, weight=1)
        self.top_toolbar = TopToolbar(
            self.root,
            self._start_tally_test,
            self._toggle_settings,
            self._toggle_details,
        )
        self.top_toolbar.grid(row=0, column=0, sticky="ew")

        self.shell = ctk.CTkFrame(self.root, corner_radius=0, fg_color=color("background"))
        self.shell.grid(row=1, column=0, sticky="nsew")
        self.shell.grid_rowconfigure(0, weight=1)
        self.shell.grid_columnconfigure(0, weight=1)

        self.workspace = ctk.CTkFrame(self.shell, fg_color="transparent", corner_radius=0)
        self.workspace.grid(row=0, column=0, sticky="nsew")
        self.workspace.grid_columnconfigure(0, weight=1)
        self.workspace.grid_rowconfigure(4, weight=1)
        self.frames["workspace"] = self.workspace

        server_url = self.settings.get("tally_server_url", "http://localhost:9000")
        self.file_controls = FileControlPanel(
            self.workspace,
            self._bank_choices(),
            self.settings.get("default_bank", "Automatic"),
            self._choose_pdf,
            self._start_extraction,
            self._start_tally_company_load,
            self._start_ledger_matching,
        )
        self.file_controls.grid(row=0, column=0, sticky="ew", padx=8, pady=(7, 3))
        self._enable_drop(self.file_controls)
        self._enable_drop(self.file_controls.file_path)

        self.summary_bar = SummaryBar(self.workspace)
        self.summary_bar.grid(row=1, column=0, sticky="ew", padx=8, pady=3)

        self.mapping_panel = InlineMappingPanel(self.workspace, self._apply_mapping, self._save_current_template)
        self.mapping_panel.grid(row=2, column=0, sticky="ew", padx=8, pady=3)
        self.mapping_panel.grid_remove()

        self.filter_toolbar = FilterToolbar(
            self.workspace,
            self._apply_filters,
            self._clear_filters,
            self._undo,
            self._redo,
            self._previous_page,
            self._next_page,
        )
        self.filter_toolbar.grid(row=3, column=0, sticky="ew", padx=8, pady=3)

        body = ctk.CTkFrame(self.workspace, fg_color="transparent")
        body.grid(row=4, column=0, sticky="nsew", padx=8, pady=3)
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=1)
        self.review_body = body
        self.review_table = EditableTransactionTable(
            body,
            self._save_table_transaction,
            int(self.settings.get("page_size", 100)),
            self._selection_changed,
        )
        self.review_table.grid(row=0, column=0, sticky="nsew")
        self.review_table.bind("<<DeleteRows>>", lambda _event: self._delete_selected())
        self.detail_panel = TransactionDetailPanel(
            body,
            self._save_detail_transaction,
            self._save_match_rule_from_transaction,
            self._ignore_detail_transaction,
            self._delete_detail_transaction,
            self._set_detail_duplicate,
            self.review_table.select_transaction,
            self._hide_details,
        )
        self.detail_panel.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.detail_panel.grid_remove()

        self.bulk_toolbar = BulkActionToolbar(
            self.workspace,
            self._bulk_assign_ledger,
            self._bulk_voucher_type,
            self._toggle_ignored,
            self._delete_selected,
            self._mark_selected_valid,
            self._export_selected,
        )
        self.bulk_toolbar.grid(row=5, column=0, sticky="ew", padx=8, pady=3)

        self.bottom_actions = BottomActionBar(
            self.workspace,
            self._start_validation,
            self._start_xml_preview,
            self._start_xml_export,
            self._start_direct_tally_import,
        )
        self.bottom_actions.grid(row=6, column=0, sticky="ew", padx=8, pady=(3, 7))

        default_folder = Path(self.settings.get("default_export_folder", "exports"))
        if not default_folder.is_absolute():
            default_folder = self.project_root / default_folder
        self.settings_drawer = SettingsDrawer(
            self.shell,
            default_folder,
            self.settings.get("appearance_mode", "Light"),
            server_url,
            self.settings.load(),
            self._start_manual_update_check,
            self._hide_settings,
            self._change_theme,
            self._save_app_settings,
            self._start_excel_export,
            self._show_mapping,
            self._backup_application_data,
            self._open_logs_folder,
        )
        self.settings_drawer.grid(row=0, column=1, sticky="nsew")
        self.settings_drawer.grid_remove()
        self.template_manager = TemplateManagerFrame(
            self.settings_drawer.templates_tab,
            self.controller.templates.list_templates,
            self._apply_template,
        )
        self.template_manager.pack(fill="both", expand=True)
        self.saved_rules_frame = SavedRulesFrame(
            self.settings_drawer.rules_tab,
            self.controller.list_matching_rules,
            self._save_matching_rule,
            self._delete_matching_rule,
        )
        self.saved_rules_frame.pack(fill="both", expand=True)
        self.import_history_frame = ImportHistoryFrame(
            self.settings_drawer.history_tab, self.controller.list_import_history
        )
        self.import_history_frame.pack(fill="both", expand=True)

        self.status_bar = StatusBar(self.root)
        self.status_bar.grid(row=2, column=0, sticky="ew")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<Control-o>", lambda _event: self._choose_pdf())
        self.root.bind("<Control-e>", lambda _event: self._start_extraction())
        self.root.bind("<Control-f>", lambda _event: self.filter_toolbar.search.focus_set())
        self.root.bind("<Control-s>", lambda _event: self.detail_panel.save())
        self.root.bind("<Control-z>", lambda _event: self._undo())
        self.root.bind("<Control-y>", lambda _event: self._redo())
        self.root.bind("<Control-Shift-V>", lambda _event: self._start_validation())
        self.root.bind("<Control-Shift-E>", lambda _event: self._start_xml_export())

    def _choose_pdf(self) -> None:
        folder = self.settings.get("default_pdf_folder", "")
        selected = filedialog.askopenfilename(
            parent=self.root,
            title="Select bank statement",
            initialdir=folder or None,
            filetypes=[("PDF files", "*.pdf")],
        )
        if selected:
            self._set_pdf(Path(selected))

    def _set_pdf(self, path: Path) -> None:
        if path.suffix.lower() != ".pdf":
            self._set_status("Choose a PDF file.", error=True)
            return
        self.selected_pdf = path
        self.file_controls.set_file(str(path))
        self._set_status(f"PDF loaded: {path.name}")

    def _enable_drop(self, widget: tk.Misc) -> None:
        try:
            from tkinterdnd2 import DND_FILES

            widget.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            widget.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _on_drop(self, event: tk.Event) -> None:
        files = self.root.tk.splitlist(event.data)  # type: ignore[attr-defined]
        if files:
            self._set_pdf(Path(files[0]))

    def _start_extraction(self) -> None:
        if self.busy:
            return
        if not self.selected_pdf:
            self._set_status("Select a bank statement PDF first.", error=True)
            return
        path = self.selected_pdf
        bank = self.file_controls.bank.get()
        password = self.file_controls.password.get()
        self._set_busy(True, f"Extracting {path.name}…")

        def work() -> None:
            try:
                result = self.controller.extract_pdf(
                    path,
                    bank,
                    password,
                    lambda current, total, message: self.worker_events.put(
                        ("extraction_progress", (current, total, message))
                    ),
                )
                self.worker_events.put(("extraction_done", (result.page_count, len(result.rows))))
            except Exception as exc:
                LOGGER.exception("Statement extraction failed")
                self.worker_events.put(("extraction_failed", exc))

        threading.Thread(target=work, daemon=True, name="pdf-extractor").start()

    def _extraction_done(self, pages: int, rows: int) -> None:
        self._set_busy(False)
        self.file_controls.password.delete(0, "end")
        extraction = self.controller.state.extraction
        assert extraction is not None
        mapping = self.controller.state.mapping
        self.mapping_panel.load(extraction.rows, mapping)
        self.file_controls.bank.set(self.controller.state.selected_bank)
        if mapping.validate():
            self.mapping_panel.grid()
            self.mapping_panel.set_expanded(True)
            self._set_status(f"Extracted {rows:,} rows from {pages} pages. Confirm column mapping.")
        else:
            self._set_status(f"Extracted {rows:,} rows from {pages} pages. Building transaction review…")
            self._start_parse(mapping)

    def _apply_mapping(self, mapping: ColumnMapping) -> None:
        errors = mapping.validate()
        if errors:
            self._set_status(" ".join(errors), error=True)
            return
        self._start_parse(mapping)

    def _start_parse(self, mapping: ColumnMapping) -> None:
        if self.busy:
            return
        self._set_busy(True, "Parsing and validating transactions…")

        def work() -> None:
            try:
                self.worker_events.put(("parse_done", self.controller.parse_transactions(mapping)))
            except Exception as exc:
                LOGGER.exception("Transaction parsing failed")
                self.worker_events.put(("parse_failed", exc))

        threading.Thread(target=work, daemon=True, name="transaction-parser").start()

    def _parse_done(self, transactions: list[Transaction], warnings: list[str]) -> None:
        self._set_busy(False)
        self.mapping_panel.set_expanded(False)
        self.mapping_panel.grid_remove()
        self.review_table.set_transactions(transactions)
        self._refresh_summary()
        suffix = f" • {len(warnings)} skipped row(s)" if warnings else ""
        self._set_status(f"{len(transactions):,} transactions extracted{suffix}")

    def _poll_worker_events(self) -> None:
        try:
            while True:
                event_name, payload = self.worker_events.get_nowait()
                self._handle_worker_event(event_name, payload)
        except queue.Empty:
            pass
        try:
            self.root.after(80, self._poll_worker_events)
        except tk.TclError:
            pass

    def _handle_worker_event(self, event_name: str, payload: object) -> None:
        if event_name == "state_changed":
            self._refresh_summary()
        elif event_name == "extraction_done":
            pages, rows = payload  # type: ignore[misc]
            self._extraction_done(pages, rows)
        elif event_name == "extraction_failed":
            self._operation_failed(payload)  # type: ignore[arg-type]
        elif event_name == "extraction_progress":
            current, total, message = payload  # type: ignore[misc]
            self.status_bar.progress.set(current / max(1, total))
            self.status_bar.set(message, current / max(1, total))
        elif event_name == "parse_done":
            transactions, warnings = payload  # type: ignore[misc]
            self._parse_done(transactions, warnings)
        elif event_name == "parse_failed":
            self._operation_failed(payload)  # type: ignore[arg-type]
        elif event_name == "tally_test_done":
            self._tally_test_done(payload)
        elif event_name == "tally_company_done":
            self._tally_company_done(payload)
        elif event_name == "ledger_match_done":
            self._ledger_match_done(payload)  # type: ignore[arg-type]
        elif event_name in {"tally_test_failed", "tally_company_failed", "ledger_match_failed"}:
            self.tally_connected = False
            self._set_busy(False)
            self.top_toolbar.set_connection("disconnected", "Tally operation failed")
            self._set_status(str(payload), error=True)
        elif event_name == "validation_done":
            self._validation_done(payload)
        elif event_name == "validation_failed":
            self._set_busy(False)
            self._set_status(f"Validation failed: {payload}", error=True)
        elif event_name == "xml_preview_done":
            self._set_busy(False)
            preview, report = payload  # type: ignore[misc]
            self._show_details()
            self.detail_panel.show_validation(report, select_tab=False)
            self.detail_panel.show_xml(preview)
            self._set_status(f"XML preview generated for {len(report.valid_transaction_ids):,} voucher(s).")
        elif event_name == "xml_export_done":
            self._set_busy(False)
            result = payload
            self.review_table.set_transactions(self.controller.state.transactions, preserve_selection=True)
            paths = ", ".join(str(path) for path in result.files)  # type: ignore[attr-defined]
            self._set_status(f"XML exported successfully: {paths}")
        elif event_name == "xml_operation_failed":
            self._set_busy(False)
            self._set_status(f"XML operation failed: {payload}", error=True)
        elif event_name == "tally_import_progress":
            current, total, message = payload  # type: ignore[misc]
            self.status_bar.set(f"Importing {current}/{total}: {message}", current / total if total else 0)
        elif event_name == "tally_import_done":
            self._set_busy(False)
            batch = payload
            self.review_table.set_transactions(self.controller.state.transactions, preserve_selection=True)
            self.import_history_frame.refresh()
            self._set_status(
                f"Tally import complete: {batch.created} created, {batch.altered} altered, {batch.failed} failed"  # type: ignore[attr-defined]
            )
        elif event_name == "excel_export_done":
            self._set_busy(False)
            self._set_status(f"Excel exported successfully: {payload}")
        elif event_name == "update_check_done":
            release, manual = payload  # type: ignore[misc]
            self._update_check_done(release, manual)
        elif event_name == "update_check_failed":
            error, manual = payload  # type: ignore[misc]
            self._update_check_failed(error, manual)
        elif event_name == "update_download_progress":
            received, total = payload  # type: ignore[misc]
            fraction = received / total if total else 0
            self.status_bar.set(f"Downloading update: {fraction:.0%}", fraction)
        elif event_name == "update_prepared":
            self._update_prepared(payload)  # type: ignore[arg-type]
        elif event_name == "update_prepare_failed":
            self._update_prepare_failed(payload)  # type: ignore[arg-type]

    def _operation_failed(self, error: Exception) -> None:
        self._set_busy(False)
        self.file_controls.password.delete(0, "end")
        if isinstance(error, PdfPasswordRequiredError):
            message = "This PDF is protected. Enter its password and extract again."
        elif isinstance(error, IncorrectPdfPasswordError):
            message = "The PDF password is incorrect."
        else:
            message = str(error)
        self._set_status(message, error=True)

    def _start_tally_test(self, server_url: str | None = None) -> None:
        if self.busy:
            return
        url = (server_url or self.settings_drawer.server_url.get()).strip()
        self.top_toolbar.set_connection("connecting")
        self._set_busy(True, "Connecting to Tally Prime…")

        def work() -> None:
            try:
                self.worker_events.put(("tally_test_done", self.controller.test_tally_connection(url)))
            except Exception as exc:
                LOGGER.exception("Tally connection test failed")
                self.worker_events.put(("tally_test_failed", exc))

        threading.Thread(target=work, daemon=True, name="tally-connection").start()

    def _tally_test_done(self, result: object) -> None:
        self.tally_connected = True
        self._set_busy(False)
        companies = [item.name for item in result.companies]  # type: ignore[attr-defined]
        self.file_controls.set_companies(companies)
        self.top_toolbar.set_connection("connected", f"Tally connected • {result.response_time_ms} ms")  # type: ignore[attr-defined]
        self.settings.save({"tally_server_url": result.server_url})  # type: ignore[attr-defined]
        self._set_status(f"Tally connected. {len(companies)} open company(s) found.")

    def _start_tally_company_load(self, company_name: str) -> None:
        if self.busy:
            return
        if company_name in {"Connect to Tally first", "No company is open", ""}:
            self._set_status("Open a company in Tally and test the connection first.", error=True)
            return
        self._set_busy(True, f"Fetching ledgers from {company_name}…")

        def work() -> None:
            try:
                self.worker_events.put(("tally_company_done", self.controller.load_tally_company(company_name)))
            except Exception as exc:
                LOGGER.exception("Tally ledger download failed")
                self.worker_events.put(("tally_company_failed", exc))

        threading.Thread(target=work, daemon=True, name="tally-ledgers").start()

    def _tally_company_done(self, data: object) -> None:
        self._set_busy(False)
        ledgers = [item.name for item in data.ledgers]  # type: ignore[attr-defined]
        bank_ledgers = [item.name for item in data.ledgers if item.is_bank_or_cash]  # type: ignore[attr-defined]
        default_bank = self.settings.get("default_bank_ledger", "")
        self.file_controls.set_ledgers(bank_ledgers or ledgers, default_bank)
        self.review_table.set_ledger_choices(ledgers)
        self.detail_panel.set_ledger_choices(ledgers)
        self.bulk_toolbar.set_ledgers(ledgers)
        self.saved_rules_frame.set_ledgers(ledgers)
        self._set_status(
            f"{data.company.name}: {len(ledgers):,} ledgers and {len(data.voucher_types)} voucher types loaded"  # type: ignore[attr-defined]
        )
        self._refresh_summary()

    def _start_ledger_matching(self, bank_ledger_name: str) -> None:
        if self.busy:
            return
        if not self.controller.state.transactions:
            self._set_status("Extract transactions before matching ledgers.", error=True)
            return
        if bank_ledger_name in {"Refresh Tally ledgers", "No bank or cash ledgers found", ""}:
            self._set_status("Select the statement bank ledger first.", error=True)
            return
        self._set_busy(True, "Matching transaction descriptions to Tally ledgers…")
        threshold = int(self.settings.get("fuzzy_matching_threshold", 78))
        suspense = self.settings.get("default_suspense_ledger", "Suspense A/c")

        def work() -> None:
            try:
                counts = self.controller.apply_ledger_matching(bank_ledger_name, threshold, suspense)
                self.worker_events.put(("ledger_match_done", counts))
            except Exception as exc:
                LOGGER.exception("Ledger matching failed")
                self.worker_events.put(("ledger_match_failed", exc))

        threading.Thread(target=work, daemon=True, name="ledger-matcher").start()

    def _ledger_match_done(self, counts: dict[str, int]) -> None:
        self._set_busy(False)
        self.settings.save({"default_bank_ledger": self.controller.state.selected_bank_ledger})
        self.review_table.set_transactions(self.controller.state.transactions, preserve_selection=True)
        self._refresh_summary()
        self._set_status(
            f"Ledger matching completed: {counts['matched']:,} matched, "
            f"{counts['rules']:,} rules, {counts['suspense']:,} suspense"
        )

    def _selection_changed(self, transaction_ids: list[str]) -> None:
        self.bulk_toolbar.set_selected(len(transaction_ids))
        if not transaction_ids:
            return
        selected = set(transaction_ids)
        transaction = next((item for item in self.controller.state.transactions if item.id in selected), None)
        if transaction:
            self.detail_panel.load(transaction, self.controller.state.selected_bank)
            if len(transaction_ids) == 1:
                self._show_details()

    def _save_table_transaction(self, transaction: Transaction) -> None:
        self.controller.save_transaction(transaction)
        self.review_table.refresh_transaction(transaction)
        self._refresh_summary()

    def _save_detail_transaction(self, transaction: Transaction) -> None:
        self.controller.save_transaction(transaction)
        self.review_table.refresh_transaction(transaction)
        self._refresh_summary()

    def _save_match_rule_from_transaction(self, transaction: Transaction) -> None:
        if not transaction.opposite_ledger:
            self._set_status("Select an opposite ledger before saving a match rule.", error=True)
            return
        rule = MatchingRule(
            pattern=transaction.description,
            ledger_name=transaction.opposite_ledger,
            match_type=RuleMatchType.CONTAINS,
            voucher_type=transaction.voucher_type,
        )
        try:
            self._save_matching_rule(rule)
            self._set_status(f"Match rule saved for {transaction.opposite_ledger}.")
        except ValueError as exc:
            self._set_status(str(exc), error=True)

    def _ignore_detail_transaction(self, transaction: Transaction) -> None:
        self.controller.set_ignored([transaction.id], not transaction.ignored)
        self.review_table.refresh_transaction(transaction)
        self._refresh_summary()

    def _delete_detail_transaction(self, transaction: Transaction) -> None:
        self._delete_ids([transaction.id])

    def _set_detail_duplicate(self, transaction: Transaction, status: DuplicateStatus) -> None:
        self.controller.set_duplicate_status([transaction.id], status)
        self.review_table.refresh_transaction(transaction)
        self._refresh_summary()

    def _bulk_assign_ledger(self, ledger_name: str) -> None:
        ids = self.review_table.selected_ids()
        if not ids or ledger_name == "Assign Ledger":
            return
        changed = self.controller.bulk_update_transactions(ids, ledger_name=ledger_name)
        for item in changed:
            self.review_table.refresh_transaction(item)
        self._refresh_summary()
        self._set_status(f"Assigned {ledger_name} to {len(changed):,} transaction(s).")

    def _bulk_voucher_type(self, voucher_type: str) -> None:
        ids = self.review_table.selected_ids()
        if not ids:
            return
        changed = self.controller.bulk_update_transactions(ids, voucher_type=VoucherType(voucher_type))
        for item in changed:
            self.review_table.refresh_transaction(item)
        self._refresh_summary()

    def _toggle_ignored(self) -> None:
        ids = self.review_table.selected_ids()
        if not ids:
            return
        selected = set(ids)
        ignore = any(not item.ignored for item in self.controller.state.transactions if item.id in selected)
        changed = self.controller.bulk_update_transactions(ids, ignored=ignore)
        for item in changed:
            self.review_table.refresh_transaction(item)
        self._refresh_summary()

    def _mark_selected_valid(self) -> None:
        ids = self.review_table.selected_ids()
        if not ids:
            return
        changed = self.controller.mark_transactions_valid(ids)
        for item in changed:
            self.review_table.refresh_transaction(item)
        self._refresh_summary()

    def _delete_selected(self) -> None:
        self._delete_ids(self.review_table.selected_ids())

    def _delete_ids(self, transaction_ids: list[str]) -> None:
        if not transaction_ids:
            return
        if not messagebox.askyesno(
            "Delete transactions",
            f"Delete {len(transaction_ids)} selected transaction(s)?",
            parent=self.root,
        ):
            return
        self.controller.delete_transactions(transaction_ids)
        self.review_table.set_transactions(self.controller.state.transactions)
        self._hide_details()
        self._refresh_summary()

    def _start_validation(self) -> None:
        if self.busy or not self.controller.state.transactions:
            return
        options = self._try_export_options()
        self._set_busy(True, "Validating transactions and detecting duplicates…")
        threshold = int(self.settings.get("duplicate_detection_sensitivity", 75))

        def work() -> None:
            try:
                matches, summary = self.controller.analyze_transactions(threshold)
                report = self.controller.validate_xml_export(options) if options else None
                self.worker_events.put(("validation_done", (matches, summary, report)))
            except Exception as exc:
                LOGGER.exception("Validation failed")
                self.worker_events.put(("validation_failed", exc))

        threading.Thread(target=work, daemon=True, name="transaction-validator").start()

    def _validation_done(self, payload: object) -> None:
        self._set_busy(False)
        matches, summary, report = payload  # type: ignore[misc]
        self.review_table.set_transactions(self.controller.state.transactions, preserve_selection=True)
        if report is not None:
            self._show_details()
            self.detail_panel.show_validation(report)
        self._refresh_summary()
        self._set_status(
            f"Validation completed: {summary.valid} valid, {summary.warnings} warnings, "
            f"{summary.invalid} errors, {len(matches)} duplicate pair(s)"
        )

    def _start_xml_preview(self) -> None:
        if self.busy:
            return
        if not any(not item.ignored for item in self.controller.state.transactions):
            self._set_status("Load at least one transaction before previewing XML.", error=True)
            return
        options = self._preview_export_options()
        if options is None:
            return
        failed_only = bool(self.settings_drawer.export_settings.failed_only.get())
        self._set_busy(True, "Generating validated XML preview…")

        def work() -> None:
            try:
                self.worker_events.put(("xml_preview_done", self.controller.preview_xml(options, failed_only)))
            except Exception as exc:
                LOGGER.exception("XML preview failed")
                self.worker_events.put(("xml_operation_failed", exc))

        threading.Thread(target=work, daemon=True, name="xml-preview").start()

    def _start_xml_export(self) -> None:
        if not self._current_action_button_states().export_enabled:
            self._set_status("Resolve critical validation errors before exporting XML.", error=True)
            return
        self._start_xml_export_for_ids(None)

    def _export_selected(self) -> None:
        ids = self.review_table.selected_ids()
        if ids:
            self._start_xml_export_for_ids(ids)

    def _start_xml_export_for_ids(self, transaction_ids: list[str] | None) -> None:
        if self.busy:
            return
        options = self._require_export_options()
        if options is None:
            return
        output = self.settings_drawer.export_settings.output_path()
        if not output.is_absolute():
            output = self.project_root / output
        failed_only = bool(self.settings_drawer.export_settings.failed_only.get())
        unmatched = self._unmatched_count(transaction_ids)
        if unmatched and not self._confirm_warning(
            "Continue XML export?",
            f"{unmatched} transactions are unmatched and currently use Suspense a/c.\n\n"
            "Do you want to continue exporting them?",
        ):
            return
        self._set_busy(True, "Validating and exporting Tally XML…")

        def work() -> None:
            try:
                result = (
                    self.controller.export_selected_xml(output, options, transaction_ids)
                    if transaction_ids is not None
                    else self.controller.export_xml(output, options, failed_only)
                )
                self.worker_events.put(("xml_export_done", result))
            except Exception as exc:
                LOGGER.exception("XML export failed")
                self.worker_events.put(("xml_operation_failed", exc))

        threading.Thread(target=work, daemon=True, name="xml-exporter").start()

    def _start_direct_tally_import(self) -> None:
        if self.busy:
            return
        if not self._current_action_button_states().tally_enabled:
            self._set_status(
                "Sending requires technically valid transactions, a Tally connection, and a selected bank ledger.",
                error=True,
            )
            return
        options = self._require_export_options()
        if options is None:
            return
        failed_only = bool(self.settings_drawer.export_settings.failed_only.get())
        unmatched = self._unmatched_count()
        if unmatched:
            if not self._confirm_warning(
                "Continue Tally import?",
                f"{unmatched} unmatched transactions will be imported using Suspense a/c.\n\nContinue?",
            ):
                return
        elif not messagebox.askyesno(
            "Send vouchers to Tally",
            f"Import validated vouchers into {options.company_name}?\n\nKeep this company open in Tally Prime.",
            parent=self.root,
        ):
            return
        self._set_busy(True, "Sending validated vouchers to Tally…")

        def progress(current: int, total: int, message: str) -> None:
            self.worker_events.put(("tally_import_progress", (current, total, message)))

        def work() -> None:
            try:
                batch = self.controller.import_xml_to_tally(options, failed_only, progress)
                self.worker_events.put(("tally_import_done", batch))
            except Exception as exc:
                LOGGER.exception("Direct Tally import failed")
                self.worker_events.put(("xml_operation_failed", exc))

        threading.Thread(target=work, daemon=True, name="tally-import").start()

    def _try_export_options(self) -> ExportOptions | None:
        try:
            return self.settings_drawer.export_settings.get_options(self.file_controls.company.get())
        except ValueError:
            return None

    def _preview_export_options(self) -> ExportOptions | None:
        company_name = self.file_controls.company.get().strip()
        if company_name in {"", "Connect to Tally first", "No company is open"}:
            company_name = "XML Preview Company"
        try:
            return self.settings_drawer.export_settings.get_options(company_name)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return None

    def _require_export_options(self) -> ExportOptions | None:
        try:
            return self.settings_drawer.export_settings.get_options(self.file_controls.company.get())
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return None

    def _apply_filters(self) -> None:
        try:
            start = self._parse_filter_date(self.filter_toolbar.date_start.get())
            end = self._parse_filter_date(self.filter_toolbar.date_end.get())
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        self.review_table.apply_filters(
            self.filter_toolbar.search.get(),
            self.filter_toolbar.direction.get(),
            voucher=self.filter_toolbar.voucher.get(),
            match=self.filter_toolbar.match.get(),
            validation=self.filter_toolbar.validation.get(),
            duplicate=self.filter_toolbar.duplicate.get(),
            date_start=start,
            date_end=end,
        )
        self._update_page_label()

    def _clear_filters(self) -> None:
        self.filter_toolbar.clear()
        self._apply_filters()

    @staticmethod
    def _parse_filter_date(value: str):
        if not value.strip():
            return None
        try:
            return datetime.strptime(value.strip(), "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError("Date filters must use YYYY-MM-DD.") from exc

    def _undo(self) -> None:
        self.review_table.undo()
        self._refresh_summary()

    def _redo(self) -> None:
        self.review_table.redo()
        self._refresh_summary()

    def _previous_page(self) -> None:
        self.review_table.previous_page()
        self._update_page_label()

    def _next_page(self) -> None:
        self.review_table.next_page()
        self._update_page_label()

    def _refresh_summary(self) -> None:
        items = [item for item in self.controller.state.transactions if not item.ignored]
        debit = sum((item.debit_amount for item in items), Decimal("0.00"))
        credit = sum((item.credit_amount for item in items), Decimal("0.00"))
        opening: Decimal | None = None
        closing: Decimal | None = None
        if items:
            first = items[0]
            if first.balance is not None:
                opening = first.balance + first.debit_amount - first.credit_amount
            balances = [item.balance for item in items if item.balance is not None]
            closing = balances[-1] if balances else None
        unmatched = sum(
            not item.opposite_ledger or item.matching_confidence == 0 or "suspense" in item.opposite_ledger.casefold()
            for item in items
        )
        errors = self.controller.get_critical_error_count(items)
        duplicates = sum(
            item.duplicate_status in {DuplicateStatus.SUSPECTED, DuplicateStatus.CONFIRMED_DUPLICATE} for item in items
        )
        valid = len(items) - errors
        self.summary_bar.update_values(
            transactions=len(items),
            debit=debit,
            credit=credit,
            opening=opening,
            closing=closing,
            unmatched=unmatched,
            errors=errors,
            duplicates=duplicates,
        )
        self.bottom_actions.set_summary(valid, errors, unmatched)
        self.update_action_button_states()
        self._update_page_label()

    def _current_action_button_states(self) -> ActionButtonStates:
        items = [item for item in self.controller.state.transactions if not item.ignored]
        return calculate_action_button_states(
            transaction_count=len(items),
            critical_error_count=self.controller.get_critical_error_count(items),
            tally_connected=self.tally_connected,
            bank_ledger_selected=bool(self.controller.state.selected_bank_ledger.strip()),
            busy=self.busy,
        )

    def update_action_button_states(self) -> None:
        """Refresh all bottom XML actions from one centralized eligibility result."""

        states = self._current_action_button_states()
        self.bottom_actions.set_action_states(
            preview_enabled=states.preview_enabled,
            export_enabled=states.export_enabled,
            tally_enabled=states.tally_enabled,
        )

    def _unmatched_count(self, transaction_ids: list[str] | None = None) -> int:
        selected = set(transaction_ids) if transaction_ids is not None else None
        return sum(
            1
            for item in self.controller.state.transactions
            if not item.ignored
            and (selected is None or item.id in selected)
            and (
                not item.opposite_ledger.strip()
                or item.matching_confidence == 0
                or "suspense" in item.opposite_ledger.casefold()
            )
        )

    def _confirm_warning(self, title: str, message: str) -> bool:
        """Show a static Continue/Cancel warning dialog."""

        result = {"continue": False}
        dialog = ctk.CTkToplevel(self.root)
        dialog.title(title)
        dialog.resizable(False, False)
        dialog.transient(self.root)

        def finish(should_continue: bool) -> None:
            result["continue"] = should_continue
            dialog.grab_release()
            dialog.destroy()

        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        ctk.CTkLabel(
            dialog,
            text=message,
            width=410,
            wraplength=390,
            justify="left",
            anchor="w",
            text_color=color("text_primary"),
        ).pack(fill="x", padx=20, pady=(20, 14))
        actions = ctk.CTkFrame(dialog, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=(0, 18))
        ctk.CTkButton(
            actions, text="Cancel", width=90, command=lambda: finish(False), **button_style("secondary")
        ).pack(side="right", padx=(8, 0))
        ctk.CTkButton(actions, text="Continue", width=90, command=lambda: finish(True), **button_style("primary")).pack(
            side="right"
        )
        dialog.update_idletasks()
        x = self.root.winfo_rootx() + max(0, (self.root.winfo_width() - dialog.winfo_reqwidth()) // 2)
        y = self.root.winfo_rooty() + max(0, (self.root.winfo_height() - dialog.winfo_reqheight()) // 2)
        dialog.geometry(f"+{x}+{y}")
        dialog.grab_set()
        dialog.focus_force()
        self.root.wait_window(dialog)
        return result["continue"]

    def _update_page_label(self) -> None:
        self.filter_toolbar.set_page(self.review_table.page + 1, self.review_table.page_count)

    def _show_details(self) -> None:
        self.review_body.grid_columnconfigure(1, minsize=370)
        self.detail_panel.grid()
        self.details_visible = True

    def _hide_details(self) -> None:
        self.detail_panel.grid_remove()
        self.review_body.grid_columnconfigure(1, minsize=0)
        self.details_visible = False

    def _toggle_details(self) -> None:
        if self.details_visible:
            self._hide_details()
        else:
            self._show_details()

    def _toggle_settings(self) -> None:
        if self.drawer_visible:
            self._hide_settings()
            return
        self.drawer_visible = True
        self.settings_drawer.grid()
        self.shell.grid_columnconfigure(1, weight=0)
        self.template_manager.refresh()
        self.saved_rules_frame.set_ledgers([item.name for item in self.controller.state.tally_ledgers])
        self.saved_rules_frame.refresh()
        self.import_history_frame.refresh()

    def _hide_settings(self) -> None:
        self.settings_drawer.grid_remove()
        self.drawer_visible = False

    def _show_mapping(self) -> None:
        if self.controller.state.extraction is None:
            self._set_status("Extract a PDF before opening column mapping.", error=True)
            return
        self.mapping_panel.load(self.controller.state.extraction.rows, self.controller.state.mapping)
        self.mapping_panel.grid()
        self.mapping_panel.set_expanded(True)
        self._hide_settings()

    def _save_current_template(self, mapping: ColumnMapping) -> None:
        bank_name = self.file_controls.bank.get()
        if bank_name in {"Automatic", "Other / Generic"}:
            bank_name = simpledialog.askstring("Save bank template", "Bank name:", parent=self.root) or ""
        try:
            template = self.controller.save_current_template(bank_name, mapping)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return
        choices = self._bank_choices()
        self.file_controls.bank.configure(values=choices)
        self.file_controls.bank.set(template.bank_name)
        self.template_manager.refresh()
        self._set_status(f"Saved reusable mapping for {template.bank_name}.")

    def _apply_template(self, template_id: str) -> None:
        try:
            mapping = self.controller.apply_template(template_id)
        except (ValueError, RuntimeError) as exc:
            self._set_status(str(exc), error=True)
            return
        extraction = self.controller.state.extraction
        assert extraction is not None
        self.mapping_panel.load(extraction.rows, mapping)
        self.mapping_panel.grid()
        self.mapping_panel.set_expanded(True)
        self.file_controls.bank.set(self.controller.state.selected_bank)
        self._hide_settings()

    def _save_matching_rule(self, rule: MatchingRule) -> None:
        self.controller.save_matching_rule(rule)
        if (
            self.controller.state.transactions
            and self.controller.state.tally_ledgers
            and self.controller.state.selected_bank_ledger
        ):
            self.controller.apply_ledger_matching(
                self.controller.state.selected_bank_ledger,
                int(self.settings.get("fuzzy_matching_threshold", 78)),
                self.settings.get("default_suspense_ledger", "Suspense A/c"),
            )
            self.review_table.set_transactions(self.controller.state.transactions, preserve_selection=True)
        self.saved_rules_frame.refresh()
        self._refresh_summary()
        self._set_status("Matching rule saved.")

    def _delete_matching_rule(self, rule_id: str) -> None:
        self.controller.delete_matching_rule(rule_id)
        self._set_status("Matching rule deleted.")

    def _start_excel_export(self) -> None:
        if self.busy or not self.controller.state.transactions:
            return
        folder = self.settings_drawer.export_settings.output_path()
        if not folder.is_absolute():
            folder = self.project_root / folder
        selected = filedialog.asksaveasfilename(
            parent=self.root,
            title="Export transactions to Excel",
            initialdir=str(folder),
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
        )
        if not selected:
            return
        self._set_busy(True, "Exporting Excel workbook…")
        threshold = int(self.settings.get("duplicate_detection_sensitivity", 75))

        def work() -> None:
            try:
                result = self.controller.export_excel(Path(selected), threshold)
                self.worker_events.put(("excel_export_done", result))
            except Exception as exc:
                LOGGER.exception("Excel export failed")
                self.worker_events.put(("xml_operation_failed", exc))

        threading.Thread(target=work, daemon=True, name="excel-exporter").start()

    def _start_automatic_update_check(self) -> None:
        if self.update_service.should_check(self.settings.load()):
            self._start_update_check(manual=False)

    def _start_manual_update_check(self) -> None:
        self._start_update_check(manual=True)

    def _start_update_check(self, *, manual: bool) -> None:
        if self.update_check_in_progress:
            if manual:
                self._set_status("An update check is already running.")
            return
        self.update_check_in_progress = True
        attempt = format_utc(utc_now())
        self.settings.save({"last_update_attempt_utc": attempt})
        self.settings_drawer.set_update_status("Checking GitHub Releases…", checking=True)
        if manual:
            self._set_status("Checking for JD Tool updates…")

        def work() -> None:
            try:
                release = self.update_service.check_latest()
                self.worker_events.put(("update_check_done", (release, manual)))
            except Exception as exc:
                LOGGER.exception("Update check failed")
                self.worker_events.put(("update_check_failed", (exc, manual)))

        threading.Thread(target=work, daemon=True, name="update-checker").start()

    def _update_check_done(self, release: UpdateRelease | None, manual: bool) -> None:
        self.update_check_in_progress = False
        self.settings.save({"last_update_check_utc": format_utc(utc_now())})
        if release is None:
            message = f"JD Tool v{self.update_service.current_version} is up to date."
            self.settings_drawer.set_update_status(message)
            if manual:
                messagebox.showinfo("No updates", message, parent=self.root)
            self._set_status(message)
            return
        self.available_update = release
        message = f"JD Tool v{release.version} is available."
        self.settings_drawer.set_update_status(message)
        self._set_status(message)
        UpdateDialog(
            self.root,
            release,
            lambda: self._start_update_download(release),
            lambda: webbrowser.open(release.release_url),
        )

    def _update_check_failed(self, error: Exception, manual: bool) -> None:
        self.update_check_in_progress = False
        if isinstance(error, UpdateNetworkError):
            status = "Could not reach GitHub Releases. JD Tool will try again later."
        else:
            status = f"Update check failed: {error}"
        self.settings_drawer.set_update_status(status)
        if manual:
            messagebox.showerror("Update check failed", status, parent=self.root)
            self._set_status(status, error=True)
        else:
            LOGGER.warning("Automatic update check suppressed UI error: %s", error)

    def _start_update_download(self, release: UpdateRelease) -> None:
        if self.busy:
            messagebox.showwarning(
                "Finish the current operation",
                "The update cannot be installed while another JD Tool operation is active.",
                parent=self.root,
            )
            return
        self._set_busy(True, f"Downloading JD Tool v{release.version}…")
        self.settings_drawer.set_update_status(f"Downloading v{release.version}…", checking=True)

        def progress(received: int, total: int) -> None:
            self.worker_events.put(("update_download_progress", (received, total)))

        def work() -> None:
            try:
                prepared = self.update_service.prepare_update(release, progress)
                self.worker_events.put(("update_prepared", prepared))
            except Exception as exc:
                LOGGER.exception("Update download or staging failed")
                self.worker_events.put(("update_prepare_failed", exc))

        threading.Thread(target=work, daemon=True, name="update-downloader").start()

    def _update_prepared(self, prepared: PreparedUpdate) -> None:
        try:
            self.settings_drawer.set_update_status(
                f"v{prepared.release.version} verified. Restarting…", checking=True
            )
            self._set_status(f"JD Tool v{prepared.release.version} verified. Restarting…")
            self.update_service.launch_updater(prepared)
        except Exception as exc:
            self._update_prepare_failed(exc)
            return
        self.root.destroy()

    def _update_prepare_failed(self, error: Exception) -> None:
        self._set_busy(False)
        message = str(error) if isinstance(error, UpdateError) else f"Unexpected update error: {error}"
        self.settings_drawer.set_update_status(message)
        messagebox.showerror("Update could not be installed", message, parent=self.root)
        self._set_status(message, error=True)
        if isinstance(error, UpdateNotSupportedError) and self.available_update is not None:
            webbrowser.open(self.available_update.release_url)

    def _show_update_result(self) -> None:
        result_path = self.project_root / "updates" / "last-result.json"
        if not result_path.is_file():
            return
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result_path.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            LOGGER.exception("Could not read updater result")
            return
        message = str(result.get("message") or "The update operation finished.")
        status = result.get("status")
        self.settings_drawer.set_update_status(message)
        self._set_status(message, error=status in {"failed", "rolled_back"})
        if status == "rolled_back":
            messagebox.showwarning("Update rolled back", message, parent=self.root)
        elif status == "failed":
            messagebox.showerror("Update failed", message, parent=self.root)
        elif status == "success":
            messagebox.showinfo("Update complete", message, parent=self.root)

    def _save_app_settings(self, values: dict[str, object]) -> None:
        server_url = str(values["tally_server_url"])
        export_folder = str(values["default_export_folder"])
        self.settings.save(values)
        self.controller.state.tally_server_url = server_url.strip()
        self.file_controls.server_url = server_url.strip()
        if self.controller.extractor.ocr_service:
            self.controller.extractor.ocr_service.update_configuration(
                OcrConfiguration(
                    executable_path=str(values["ocr_executable_path"]),
                    language=str(values["ocr_language"]),
                    dpi=int(values["ocr_dpi"]),
                    page_segmentation_mode=int(self.settings.get("ocr_page_segmentation_mode", 6)),
                )
            )
        self.settings_drawer.export_settings.output_folder.delete(0, "end")
        self.settings_drawer.export_settings.output_folder.insert(0, export_folder.strip())
        self._set_status("Application settings saved.")

    def _backup_application_data(self) -> None:
        selected = filedialog.askdirectory(parent=self.root, title="Choose backup folder")
        if not selected:
            return
        try:
            target = BackupService(self.project_root).create(Path(selected), int(self.settings.get("backup_keep", 7)))
            self._set_status(f"Backup created: {target}")
        except OSError as exc:
            self._set_status(f"Backup failed: {exc}", error=True)

    def _open_logs_folder(self) -> None:
        folder = self.project_root / "logs"
        if not folder.exists():
            self._set_status("The logs folder does not exist yet.", error=True)
            return
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
        except OSError as exc:
            self._set_status(f"Could not open logs folder: {exc}", error=True)

    def _change_theme(self, mode: str) -> None:
        ctk.set_appearance_mode(mode)
        self._configure_style()
        self.review_table.configure_tags()
        self.settings.save({"appearance_mode": mode})

    def _start_automatic_backup(self) -> None:
        if not self.settings.get("automatic_backup", False):
            return

        def work() -> None:
            try:
                folder = Path(str(self.settings.get("backup_folder", "backups")))
                if not folder.is_absolute():
                    folder = self.project_root / folder
                target = BackupService(self.project_root).create_if_due(
                    folder, int(self.settings.get("backup_keep", 7))
                )
                if target:
                    LOGGER.info("Automatic application-data backup completed")
            except OSError:
                LOGGER.exception("Automatic application-data backup failed")

        threading.Thread(target=work, daemon=True, name="automatic-backup").start()

    def _bank_choices(self) -> list[str]:
        template_banks = [item.bank_name for item in self.controller.templates.list_templates()]
        return list(dict.fromkeys([*BANKS, *template_banks]))

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self.busy = busy
        self.top_toolbar.set_busy(busy)
        self.file_controls.set_busy(busy)
        self.bottom_actions.set_busy(busy)
        self.settings_drawer.set_operation_busy(busy or self.update_check_in_progress)
        self.status_bar.progress.configure(mode="determinate")
        self.status_bar.progress.set(0)
        if message:
            self.status_bar.message.configure(text_color=color("text_secondary"))
            self.status_bar.set(message, 0 if busy else None)
        if busy:
            self.update_action_button_states()
        else:
            self._refresh_summary()

    def _set_status(self, message: str, error: bool = False) -> None:
        self.status_bar.set(message)
        self.status_bar.message.configure(text_color=color("danger") if error else color("text_secondary"))

    def _close(self) -> None:
        if self.busy and not messagebox.askyesno(
            "Operation in progress",
            "Close while a background operation is running?",
            parent=self.root,
        ):
            return
        self.root.destroy()
