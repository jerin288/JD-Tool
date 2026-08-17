import unittest

from app.models.export import ExportValidationReport
from app.views.main_window import BankStatementApplication


class _PreviewPanel:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def show_validation(self, report: ExportValidationReport, *, select_tab: bool = True) -> None:
        self.calls.append(("validation", report, select_tab))

    def show_xml(self, xml_text: str) -> None:
        self.calls.append(("xml", xml_text))


class XmlPreviewUiTests(unittest.TestCase):
    def test_preview_completion_does_not_switch_to_issues_tab(self) -> None:
        app = object.__new__(BankStatementApplication)
        panel = _PreviewPanel()
        app.detail_panel = panel
        app._set_busy = lambda _busy: None
        app._show_details = lambda: None
        app._set_status = lambda _message, **_kwargs: None
        report = ExportValidationReport((), ("transaction-1",), ())

        app._handle_worker_event("xml_preview_done", ("<ENVELOPE />", report))

        self.assertEqual(
            panel.calls,
            [
                ("validation", report, False),
                ("xml", "<ENVELOPE />"),
            ],
        )


if __name__ == "__main__":
    unittest.main()
