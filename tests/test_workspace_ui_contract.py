import ast
import inspect
import unittest
from pathlib import Path

from app.views.editable_table import EditableTransactionTable
from app.views.inline_mapping_panel import InlineMappingPanel
from app.views.transaction_detail_panel import TransactionDetailPanel
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


class WorkspaceUiContractTests(unittest.TestCase):
    def test_transaction_table_exposes_required_accounting_columns(self) -> None:
        fields = [field for field, _title, _width in EditableTransactionTable.COLUMNS]
        self.assertEqual(
            fields,
            [
                "_selected",
                "transaction_date",
                "value_date",
                "description",
                "reference_number",
                "debit_amount",
                "credit_amount",
                "balance",
                "opposite_ledger",
                "voucher_type",
                "matching_confidence",
                "validation_status",
            ],
        )

    def test_workspace_is_composed_from_reusable_frames(self) -> None:
        components = {
            TopToolbar,
            FileControlPanel,
            SummaryBar,
            FilterToolbar,
            InlineMappingPanel,
            EditableTransactionTable,
            TransactionDetailPanel,
            BulkActionToolbar,
            BottomActionBar,
            SettingsDrawer,
            StatusBar,
        }
        self.assertEqual(len(components), 11)

    def test_main_window_constructor_calls_match_component_signatures(self) -> None:
        source_path = Path(__file__).parents[1] / "app" / "views" / "main_window.py"
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        components = {
            "TopToolbar": TopToolbar,
            "FileControlPanel": FileControlPanel,
            "SettingsDrawer": SettingsDrawer,
        }
        calls = {
            node.func.id: node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in components
        }
        for name, component in components.items():
            parameters = list(inspect.signature(component.__init__).parameters.values())[1:]
            positional = [
                parameter
                for parameter in parameters
                if parameter.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}
            ]
            self.assertIn(name, calls)
            self.assertEqual(len(calls[name].args), len(positional), f"{name} constructor call is out of sync")

    def test_header_uses_jd_tool_branding_without_workflow_breadcrumb(self) -> None:
        components_path = Path(__file__).parents[1] / "app" / "views" / "workspace_components.py"
        main_window_path = Path(__file__).parents[1] / "app" / "views" / "main_window.py"
        components_source = components_path.read_text(encoding="utf-8")
        main_window_source = main_window_path.read_text(encoding="utf-8")
        self.assertIn('text="JD Tool"', components_source)
        self.assertIn('self.root.title("JD Tool")', main_window_source)
        self.assertIn("self.root.iconphoto(True, self.window_icon)", main_window_source)
        self.assertNotIn("Bank Statement → Tally Prime Converter", components_source)
        self.assertNotIn("Open PDF  ›  Review", components_source)

    def test_tally_connect_action_is_in_header_before_details_and_settings(self) -> None:
        top_toolbar_source = inspect.getsource(TopToolbar)
        file_controls_source = inspect.getsource(FileControlPanel)

        connect_position = top_toolbar_source.index('text="Tally Connect"')
        details_position = top_toolbar_source.index('text="Details"')
        settings_position = top_toolbar_source.index('text="Settings"')
        self.assertLess(connect_position, details_position)
        self.assertLess(details_position, settings_position)
        self.assertNotIn('text="Test"', file_controls_source)

    def test_stale_inline_editor_is_destroyed(self) -> None:
        class StaleEditor:
            destroyed = False

            def winfo_exists(self) -> bool:
                return True

            def destroy(self) -> None:
                self.destroyed = True

        table = object.__new__(EditableTransactionTable)
        table._editor = object()
        stale_editor = StaleEditor()

        table._commit_edit(stale_editor, object(), "opposite_ledger")

        self.assertTrue(stale_editor.destroyed)

    def test_combobox_popdown_counts_as_part_of_inline_editor(self) -> None:
        class WidgetPath:
            def __init__(self, path: str) -> None:
                self.path = path

            def __str__(self) -> str:
                return self.path

        editor = WidgetPath(".!table.!combobox")
        popdown = WidgetPath(".!table.!combobox.popdown.f.l")
        outside = WidgetPath(".!details.!entry")

        self.assertTrue(EditableTransactionTable._widget_belongs_to_editor(popdown, editor))
        self.assertFalse(EditableTransactionTable._widget_belongs_to_editor(outside, editor))


if __name__ == "__main__":
    unittest.main()
