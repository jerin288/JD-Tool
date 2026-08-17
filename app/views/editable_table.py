"""High-density editable transaction table for the single-window workspace."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from tkinter import messagebox, ttk

import customtkinter as ctk

from app.models.enums import DuplicateStatus, ImportStatus, ValidationStatus, VoucherType
from app.models.transaction import Transaction
from app.utils.amounts import format_decimal, parse_decimal
from app.utils.ledger_names import is_numeric_ledger_reference
from app.views.theme import COLORS, DARK_COLORS


@dataclass(slots=True)
class EditCommand:
    transaction: Transaction
    field_name: str
    old_value: object
    new_value: object


class EditableTransactionTable(ttk.Frame):
    """Paginated Treeview with inline editing, filters, clipboard, and undo/redo."""

    VOUCHER_BADGES = {
        VoucherType.PAYMENT: "🔴 Payment",
        VoucherType.RECEIPT: "🟢 Receipt",
        VoucherType.CONTRA: "🔵 Contra",
    }

    COLUMNS = (
        ("_selected", "Select", 48),
        ("transaction_date", "Date", 94),
        ("value_date", "Value Date", 94),
        ("description", "Description", 280),
        ("reference_number", "Reference", 110),
        ("debit_amount", "Debit (Dr)", 96),
        ("credit_amount", "Credit (Cr)", 96),
        ("balance", "Balance", 100),
        ("opposite_ledger", "Ledger", 170),
        ("voucher_type", "Voucher Type", 108),
        ("matching_confidence", "Match %", 72),
        ("validation_status", "Status", 120),
    )
    READ_ONLY_FIELDS = {"_selected", "matching_confidence", "validation_status"}

    def __init__(
        self,
        master: tk.Misc,
        on_save: Callable[[Transaction], None],
        page_size: int = 100,
        on_selection_changed: Callable[[list[str]], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.on_save = on_save
        self.on_selection_changed = on_selection_changed or (lambda _ids: None)
        self.page_size = page_size
        self.transactions: list[Transaction] = []
        self._transaction_by_id: dict[str, Transaction] = {}
        self.filtered: list[Transaction] = []
        self.page = 0
        self.search_text = ""
        self.direction_filter = "All"
        self.status_filter = "All rows"
        self.voucher_filter = "All vouchers"
        self.match_filter = "All matches"
        self.validation_filter = "All validation"
        self.duplicate_filter = "All duplicates"
        self.date_start: date | None = None
        self.date_end: date | None = None
        self.undo_stack: list[EditCommand] = []
        self.redo_stack: list[EditCommand] = []
        self.checked_ids: set[str] = set()
        self.ledger_choices: list[str] = []
        self._editor: tk.Widget | None = None
        self._editor_context: tuple[Transaction, str] | None = None
        self._editor_open_event_serial: int | None = None
        self._clicked_column = 1
        self._refreshing = False

        column_ids = [column[0] for column in self.COLUMNS]
        self.tree = ttk.Treeview(self, columns=column_ids, show="headings", selectmode="extended")
        for column_id, title, width in self.COLUMNS:
            anchor = (
                "center"
                if column_id
                in {
                    "_selected",
                    "transaction_date",
                    "value_date",
                    "voucher_type",
                    "validation_status",
                }
                else "e"
                if column_id in {"debit_amount", "credit_amount", "balance", "matching_confidence"}
                else "w"
            )
            self.tree.heading(
                column_id,
                text=title,
                command=self.select_all_filtered if column_id == "_selected" else lambda c=column_id: self.sort_by(c),
            )
            self.tree.column(
                column_id,
                width=width,
                minwidth=38 if column_id == "_selected" else 68,
                anchor=anchor,
                stretch=column_id in {"description", "opposite_ledger"},
            )
        self.configure_tags()
        vertical = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.tree.bind("<Double-1>", self._begin_edit)
        self.tree.bind("<Button-1>", self._remember_cell, add="+")
        self.tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.tree.bind("<Delete>", lambda _event: self.event_generate("<<DeleteRows>>"))
        self.tree.bind("<Control-a>", self._select_all_event)
        self.tree.bind("<Control-c>", self._copy_selected)
        self.tree.bind("<Control-v>", self._paste_cells)
        self._editor_toplevel = self.winfo_toplevel()
        self._outside_click_binding = self._editor_toplevel.bind(
            "<Button-1>", self._dismiss_editor_on_outside_click, add="+"
        )

    def destroy(self) -> None:
        """Remove the application-level editor binding with this table."""

        self._cancel_edit()
        try:
            if self._outside_click_binding:
                self._editor_toplevel.unbind("<Button-1>", self._outside_click_binding)
        except tk.TclError:
            pass
        super().destroy()

    def configure_tags(self) -> None:
        """Apply striped and semantic row colours for the active appearance mode."""

        palette = DARK_COLORS if ctk.get_appearance_mode() == "Dark" else COLORS
        self.tree.tag_configure("even", background=palette["surface"], foreground=palette["text_primary"])
        self.tree.tag_configure("odd", background=palette["table_alternate"], foreground=palette["text_primary"])
        self.tree.tag_configure("invalid", background=palette["danger_background"], foreground=palette["danger"])
        self.tree.tag_configure("ignored", background=palette["surface_secondary"], foreground=palette["text_muted"])
        self.tree.tag_configure(
            "unmatched", background=palette["unmatched_background"], foreground=palette["text_primary"]
        )
        self.tree.tag_configure("medium", background=palette["warning_background"], foreground=palette["text_primary"])
        self.tree.tag_configure(
            "duplicate", background=palette["duplicate_background"], foreground=palette["text_primary"]
        )

    def set_transactions(self, transactions: list[Transaction], preserve_selection: bool = False) -> None:
        self.transactions = transactions
        self._transaction_by_id = {item.id: item for item in transactions}
        if not preserve_selection:
            self.checked_ids.clear()
            self.page = 0
        else:
            existing = {item.id for item in transactions}
            self.checked_ids.intersection_update(existing)
        self.apply_filters()

    def set_ledger_choices(self, ledger_names: list[str]) -> None:
        self.ledger_choices = list(
            dict.fromkeys(
                name.strip()
                for name in ledger_names
                if name.strip() and not is_numeric_ledger_reference(name)
            )
        )

    def apply_filters(
        self,
        search: str | None = None,
        direction: str | None = None,
        status_filter: str | None = None,
        *,
        voucher: str | None = None,
        match: str | None = None,
        validation: str | None = None,
        duplicate: str | None = None,
        date_start: date | None = None,
        date_end: date | None = None,
    ) -> None:
        if search is not None:
            self.search_text = search.strip().lower()
        if direction is not None:
            self.direction_filter = direction
        if status_filter is not None:
            self.status_filter = status_filter
        if voucher is not None:
            self.voucher_filter = voucher
        if match is not None:
            self.match_filter = match
        if validation is not None:
            self.validation_filter = validation
        if duplicate is not None:
            self.duplicate_filter = duplicate
        self.date_start = date_start
        self.date_end = date_end

        result = list(self.transactions)
        if self.search_text:
            result = [
                item
                for item in result
                if self.search_text
                in " ".join((item.description, item.reference_number, item.opposite_ledger, item.narration)).lower()
            ]
        if self.direction_filter == "Debit":
            result = [item for item in result if item.debit_amount]
        elif self.direction_filter == "Credit":
            result = [item for item in result if item.credit_amount]
        if self.voucher_filter not in {"All", "All vouchers"}:
            result = [item for item in result if item.voucher_type.value == self.voucher_filter]
        if self.match_filter == "Matched":
            result = [item for item in result if item.opposite_ledger and item.matching_confidence > 0]
        elif self.match_filter == "Unmatched":
            result = [item for item in result if not item.opposite_ledger or item.matching_confidence == 0]
        if self.validation_filter == "Valid":
            result = [item for item in result if item.validation_status == ValidationStatus.VALID]
        elif self.validation_filter in {"Error", "Invalid"}:
            result = [item for item in result if item.validation_status == ValidationStatus.INVALID]
        elif self.validation_filter == "Warning":
            result = [item for item in result if item.validation_status == ValidationStatus.WARNING]
        if self.duplicate_filter == "Duplicates":
            result = [
                item
                for item in result
                if item.duplicate_status in {DuplicateStatus.SUSPECTED, DuplicateStatus.CONFIRMED_DUPLICATE}
            ]
        elif self.duplicate_filter == "Unique":
            result = [item for item in result if item.duplicate_status == DuplicateStatus.CONFIRMED_UNIQUE]
        if self.date_start:
            result = [item for item in result if item.transaction_date and item.transaction_date >= self.date_start]
        if self.date_end:
            result = [item for item in result if item.transaction_date and item.transaction_date <= self.date_end]

        if self.status_filter == "Possible duplicates":
            result = [item for item in result if item.duplicate_status == DuplicateStatus.SUSPECTED]
        elif self.status_filter == "Invalid":
            result = [item for item in result if item.validation_status == ValidationStatus.INVALID]
        elif self.status_filter == "Unmatched":
            result = [item for item in result if not item.opposite_ledger or item.matching_confidence == 0]
        elif self.status_filter == "Ignored":
            result = [item for item in result if item.ignored]
        elif self.status_filter == "Failed import":
            result = [item for item in result if item.import_status == ImportStatus.FAILED]
        self.filtered = result
        maximum_page = max(0, (len(result) - 1) // self.page_size)
        self.page = min(self.page, maximum_page)
        self.refresh()

    def refresh(self) -> None:
        self._refreshing = True
        self.tree.delete(*self.tree.get_children())
        start = self.page * self.page_size
        for visible_index, item in enumerate(self.filtered[start : start + self.page_size]):
            self._insert_item(item, visible_index)
        visible_checked = [
            item.id for item in self.filtered[start : start + self.page_size] if item.id in self.checked_ids
        ]
        if visible_checked:
            self.tree.selection_set(visible_checked)
        self._refreshing = False

    def refresh_transaction(self, transaction: Transaction) -> None:
        if not self.tree.exists(transaction.id):
            return
        tag = self._row_tag(transaction) or ("odd" if self.tree.index(transaction.id) % 2 else "even")
        self.tree.item(transaction.id, values=self._row_values(transaction), tags=(tag,))

    def _insert_item(self, item: Transaction, visible_index: int) -> None:
        tag = self._row_tag(item) or ("odd" if visible_index % 2 else "even")
        self.tree.insert("", "end", iid=item.id, values=self._row_values(item), tags=(tag,))

    def _row_values(self, item: Transaction) -> tuple[object, ...]:
        status = "Not checked"
        if item.import_status == ImportStatus.FAILED:
            status = "✕ Import failed"
        elif item.duplicate_status in {DuplicateStatus.SUSPECTED, DuplicateStatus.CONFIRMED_DUPLICATE}:
            status = "⚠ Duplicate"
        elif item.ignored:
            status = "— Ignored"
        elif item.validation_status == ValidationStatus.INVALID:
            status = "✕ Error"
        elif not item.opposite_ledger or item.matching_confidence == 0:
            status = "⚠ Unmatched"
        elif item.validation_status == ValidationStatus.WARNING:
            status = "⚠ Warning"
        elif item.validation_status == ValidationStatus.VALID:
            status = "✓ Valid"
        return (
            "☑" if item.id in self.checked_ids else "☐",
            item.transaction_date.isoformat() if item.transaction_date else "",
            item.value_date.isoformat() if item.value_date else "",
            item.description,
            item.reference_number,
            format_decimal(item.debit_amount),
            format_decimal(item.credit_amount),
            format_decimal(item.balance),
            item.opposite_ledger,
            self.VOUCHER_BADGES.get(item.voucher_type, item.voucher_type.value),
            f"{item.matching_confidence:.0f}%" if item.opposite_ledger else "0%",
            status,
        )

    @staticmethod
    def _row_tag(item: Transaction) -> str:
        if item.ignored:
            return "ignored"
        if item.validation_status == ValidationStatus.INVALID or item.import_status == ImportStatus.FAILED:
            return "invalid"
        if item.duplicate_status in {DuplicateStatus.SUSPECTED, DuplicateStatus.CONFIRMED_DUPLICATE}:
            return "duplicate"
        if not item.opposite_ledger or item.matching_confidence == 0:
            return "unmatched"
        if item.matching_confidence < Decimal("85"):
            return "medium"
        return ""

    @property
    def page_count(self) -> int:
        return max(1, (len(self.filtered) + self.page_size - 1) // self.page_size)

    def previous_page(self) -> None:
        if self.page > 0:
            self.page -= 1
            self.refresh()

    def next_page(self) -> None:
        if self.page + 1 < self.page_count:
            self.page += 1
            self.refresh()

    def selected_ids(self) -> list[str]:
        ordered = [item.id for item in self.transactions if item.id in self.checked_ids]
        return ordered or list(self.tree.selection())

    def select_all_filtered(self) -> None:
        ids = {item.id for item in self.filtered}
        if ids and ids.issubset(self.checked_ids):
            self.checked_ids.difference_update(ids)
        else:
            self.checked_ids.update(ids)
        self.refresh()
        self.on_selection_changed(self.selected_ids())

    def clear_selection(self) -> None:
        self.checked_ids.clear()
        self.tree.selection_remove(self.tree.selection())
        self.refresh()
        self.on_selection_changed([])

    def select_transaction(self, transaction_id: str) -> None:
        for index, item in enumerate(self.filtered):
            if item.id == transaction_id:
                self.page = index // self.page_size
                self.checked_ids = {transaction_id}
                self.refresh()
                self.tree.selection_set(transaction_id)
                self.tree.focus(transaction_id)
                self.tree.see(transaction_id)
                self.on_selection_changed([transaction_id])
                return

    def sort_by(self, field_name: str) -> None:
        if field_name == "_selected":
            return

        def key(item: Transaction):
            value = getattr(item, field_name)
            return (value is None, value)

        self.filtered.sort(key=key)
        self.refresh()

    def undo(self) -> None:
        if not self.undo_stack:
            return
        command = self.undo_stack.pop()
        setattr(command.transaction, command.field_name, command.old_value)
        self.redo_stack.append(command)
        self.on_save(command.transaction)
        self.refresh_transaction(command.transaction)

    def redo(self) -> None:
        if not self.redo_stack:
            return
        command = self.redo_stack.pop()
        setattr(command.transaction, command.field_name, command.new_value)
        self.undo_stack.append(command)
        self.on_save(command.transaction)
        self.refresh_transaction(command.transaction)

    def _remember_cell(self, event: tk.Event) -> None:
        token = self.tree.identify_column(event.x)
        if token:
            self._clicked_column = max(0, int(token[1:]) - 1)
        if self._clicked_column == 0:
            row_id = self.tree.identify_row(event.y)
            if row_id:
                if row_id in self.checked_ids:
                    self.checked_ids.remove(row_id)
                    self.tree.selection_remove(row_id)
                else:
                    self.checked_ids.add(row_id)
                    self.tree.selection_add(row_id)
                self.refresh_transaction(self._transaction_by_id[row_id])
                self.on_selection_changed(self.selected_ids())

    def _selection_changed(self, _event: tk.Event | None = None) -> None:
        if self._refreshing:
            return
        visible = set(self.tree.get_children())
        selected = set(self.tree.selection())
        self.checked_ids.difference_update(visible - selected)
        self.checked_ids.update(selected)
        for row_id in visible:
            item = self._transaction_by_id.get(row_id)
            if item:
                self.refresh_transaction(item)
        self.on_selection_changed(self.selected_ids())

    def _select_all_event(self, _event: tk.Event) -> str:
        self.select_all_filtered()
        return "break"

    def _begin_edit(self, event: tk.Event) -> None:
        if self.tree.identify_region(event.x, event.y) != "cell":
            return
        row_id = self.tree.identify_row(event.y)
        column_token = self.tree.identify_column(event.x)
        if not row_id or not column_token:
            return
        column_index = int(column_token[1:]) - 1
        field_name = self.COLUMNS[column_index][0]
        if field_name in self.READ_ONLY_FIELDS:
            return
        self._finish_active_editor()
        if self._editor is not None:
            return
        x, y, width, height = self.tree.bbox(row_id, column_token)
        transaction = self._transaction_by_id[row_id]
        current_value = self.tree.set(row_id, field_name)
        if field_name == "voucher_type":
            editor = ttk.Combobox(self.tree, values=[item.value for item in VoucherType], state="readonly")
            editor.set(transaction.voucher_type.value)
        elif field_name == "opposite_ledger" and self.ledger_choices:
            editor = ttk.Combobox(self.tree, values=self.ledger_choices)
            editor.set(current_value)
        else:
            editor = ttk.Entry(self.tree)
            editor.insert(0, current_value)
        self._editor = editor
        self._editor_context = (transaction, field_name)
        self._editor_open_event_serial = getattr(event, "serial", None)
        editor.place(x=x, y=y, width=width, height=height)
        editor.focus_set()
        editor.bind("<Return>", lambda _event: self._commit_edit(editor, transaction, field_name))
        editor.bind("<Escape>", lambda _event: self._cancel_edit())
        editor.bind("<FocusOut>", lambda _event: self._commit_edit(editor, transaction, field_name))
        if isinstance(editor, ttk.Combobox):
            editor.bind(
                "<<ComboboxSelected>>",
                lambda _event: self._commit_edit(editor, transaction, field_name),
            )

    def _finish_active_editor(self) -> None:
        editor = self._editor
        context = self._editor_context
        if editor is None:
            return
        if context is None:
            self._cancel_edit()
            return
        self._commit_edit(editor, *context)

    def _dismiss_editor_on_outside_click(self, event: tk.Event) -> None:
        """Commit the inline editor when a click lands anywhere outside it."""

        editor = self._editor
        context = self._editor_context
        if editor is None or context is None:
            return
        if getattr(event, "serial", None) == self._editor_open_event_serial:
            return
        if self._widget_belongs_to_editor(getattr(event, "widget", None), editor):
            return
        # Let the clicked control process its own event first. Capture this exact
        # editor so a later callback can never close a newly opened cell editor.
        self.after_idle(lambda: self._commit_edit(editor, *context))

    @staticmethod
    def _widget_belongs_to_editor(widget: object, editor: tk.Widget) -> bool:
        if widget is editor:
            return True
        if widget is None:
            return False
        editor_path = str(editor)
        widget_path = str(widget)
        return widget_path.startswith(f"{editor_path}.")

    def _commit_edit(self, editor: tk.Widget, transaction: Transaction, field_name: str) -> None:
        if editor is not self._editor:
            # A deferred FocusOut from an older combobox must not leave its
            # overlay (and selected-looking text) on top of the Treeview.
            try:
                if editor.winfo_exists():
                    editor.destroy()
            except tk.TclError:
                pass
            return
        raw_value = editor.get()  # type: ignore[attr-defined]
        old_value = getattr(transaction, field_name)
        try:
            new_value = self._convert_value(field_name, raw_value)
        except ValueError as exc:
            messagebox.showerror("Invalid value", str(exc), parent=self)
            editor.focus_set()
            return
        editor.destroy()
        self._editor = None
        self._editor_context = None
        self._editor_open_event_serial = None
        if old_value == new_value:
            return
        setattr(transaction, field_name, new_value)
        if field_name == "opposite_ledger":
            transaction.matching_confidence = Decimal("100") if new_value else Decimal("0")
            transaction.matching_method = "Manual" if new_value else ""
        transaction.validation_status = ValidationStatus.UNCHECKED
        self.undo_stack.append(EditCommand(transaction, field_name, old_value, new_value))
        self.redo_stack.clear()
        self.on_save(transaction)
        self.refresh_transaction(transaction)

    def _cancel_edit(self) -> None:
        if self._editor:
            self._editor.destroy()
            self._editor = None
        self._editor_context = None
        self._editor_open_event_serial = None

    def _copy_selected(self, _event: tk.Event) -> str:
        selected = set(self.selected_ids())
        rows = []
        for item in self.transactions:
            if item.id in selected:
                rows.append("\t".join(str(value) for value in self._row_values(item)[1:]))
        if rows:
            self.clipboard_clear()
            self.clipboard_append("\n".join(rows))
        return "break"

    def _paste_cells(self, _event: tk.Event) -> str:
        try:
            clipboard = self.clipboard_get()
        except tk.TclError:
            return "break"
        focus_id = self.tree.focus() or next(iter(self.tree.selection()), "")
        if not focus_id:
            return "break"
        visible_ids = list(self.tree.get_children())
        if focus_id not in visible_ids:
            return "break"
        row_start = visible_ids.index(focus_id)
        changed: set[str] = set()
        for row_offset, values in enumerate(line.split("\t") for line in clipboard.splitlines()):
            if row_start + row_offset >= len(visible_ids):
                break
            transaction = self._transaction_by_id[visible_ids[row_start + row_offset]]
            for column_offset, raw_value in enumerate(values):
                column_index = self._clicked_column + column_offset
                if column_index >= len(self.COLUMNS):
                    break
                field_name = self.COLUMNS[column_index][0]
                if field_name in self.READ_ONLY_FIELDS:
                    continue
                try:
                    new_value = self._convert_value(field_name, raw_value)
                except ValueError:
                    continue
                old_value = getattr(transaction, field_name)
                if old_value != new_value:
                    setattr(transaction, field_name, new_value)
                    self.undo_stack.append(EditCommand(transaction, field_name, old_value, new_value))
                    changed.add(transaction.id)
            if transaction.id in changed:
                self.on_save(transaction)
                self.refresh_transaction(transaction)
        if changed:
            self.redo_stack.clear()
        return "break"

    @staticmethod
    def _convert_value(field_name: str, value: str) -> object:
        if field_name in {"debit_amount", "credit_amount", "balance"}:
            return None if field_name == "balance" and not value.strip() else parse_decimal(value)
        if field_name in {"transaction_date", "value_date"}:
            if not value.strip() and field_name == "value_date":
                return None
            try:
                return datetime.strptime(value.strip(), "%Y-%m-%d").date()
            except ValueError as exc:
                raise ValueError("Dates must use YYYY-MM-DD format.") from exc
        if field_name == "voucher_type":
            return VoucherType(value)
        return value.strip()
