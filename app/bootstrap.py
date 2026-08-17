"""Dependency composition root."""

from __future__ import annotations

from pathlib import Path

from app.controllers.app_controller import AppController
from app.database.manager import DatabaseManager
from app.repositories.import_history_repository import ImportHistoryRepository
from app.repositories.matching_rule_repository import MatchingRuleRepository
from app.repositories.transaction_repository import TransactionRepository
from app.services.bank_template_service import BankTemplateService
from app.services.duplicate_detector import DuplicateDetector
from app.services.excel_exporter import ExcelExporter
from app.services.ledger_matcher import LedgerMatcher
from app.services.ocr_service import OcrConfiguration, OcrService
from app.services.pdf_extractor import PdfExtractor
from app.services.settings_service import SettingsService
from app.services.tally_client import TallyClient
from app.services.transaction_parser import TransactionParser
from app.services.update_service import UpdateService
from app.services.validation_service import ValidationService
from app.services.xml_exporter import TallyXmlExporter


def build_application(project_root: Path):
    """Build the fully wired UI, keeping construction in one testable location."""
    from app.views.main_window import BankStatementApplication

    database = DatabaseManager(project_root / "data" / "bank_converter.db")
    database.initialize()
    settings = SettingsService(project_root / "config" / "settings.json")
    settings.load()
    ocr = OcrService(
        OcrConfiguration(
            executable_path=settings.get("ocr_executable_path", ""),
            language=settings.get("ocr_language", "eng"),
            dpi=int(settings.get("ocr_dpi", 300)),
            page_segmentation_mode=int(settings.get("ocr_page_segmentation_mode", 6)),
        )
    )
    controller = AppController(
        PdfExtractor(ocr),
        TransactionParser(),
        TransactionRepository(database),
        BankTemplateService(project_root / "config" / "bank_templates"),
        DuplicateDetector(),
        ValidationService(),
        ExcelExporter(),
        MatchingRuleRepository(database),
        LedgerMatcher(),
        TallyXmlExporter(),
        ImportHistoryRepository(database),
        TallyClient,
    )
    return BankStatementApplication(
        controller,
        settings,
        project_root,
        update_service=UpdateService(project_root),
    )
