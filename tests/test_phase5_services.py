import logging
import sys
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from app.services.backup_service import BackupService
from app.services.ocr_service import OcrConfiguration, OcrService, TesseractNotFoundError
from app.services.pdf_extractor import PdfExtractor
from app.services.settings_service import SettingsService
from app.utils.logging_config import SensitiveDataFilter
from app.utils.runtime_paths import RuntimePaths


class Phase5ServiceTests(unittest.TestCase):
    def test_ocr_data_is_reconstructed_without_statement_logging(self) -> None:
        data = {
            "text": ["Date", "Description", "Debit", "01/08/2026", "Charges", "17.70"],
            "conf": ["95", "92", "93", "90", "89", "91"],
            "left": [10, 100, 300, 10, 100, 300],
            "top": [10, 10, 10, 30, 30, 30],
            "block_num": [1] * 6,
            "par_num": [1] * 6,
            "line_num": [1, 1, 1, 2, 2, 2],
        }
        words = OcrService._words_from_data(data, 2.0)
        self.assertEqual(words[3]["x0"], 5.0)
        self.assertEqual(OcrService._text_from_words(words).splitlines()[1], "01/08/2026 Charges 17.70")

    def test_missing_tesseract_has_actionable_message(self) -> None:
        service = OcrService(OcrConfiguration(executable_path="Z:/missing/tesseract.exe"))
        with patch("app.services.ocr_service.shutil.which", return_value=None), patch(
            "app.services.ocr_service.Path.is_file", return_value=False
        ):
            with self.assertRaisesRegex(TesseractNotFoundError, "Settings > App"):
                service.resolve_executable()

    def test_ocr_rows_preserve_detected_statement_columns(self) -> None:
        words = [
            {"text": "Transaction", "x0": 10, "top": 10},
            {"text": "Particulars", "x0": 130, "top": 10},
            {"text": "Withdrawals", "x0": 300, "top": 10},
            {"text": "Deposits", "x0": 400, "top": 10},
            {"text": "Balance", "x0": 500, "top": 10},
            {"text": "01-Aug-2026", "x0": 10, "top": 30},
            {"text": "Charges", "x0": 130, "top": 30},
            {"text": "17.70", "x0": 300, "top": 30},
            {"text": "16238.13", "x0": 500, "top": 30},
        ]
        rows = PdfExtractor._ocr_words_to_rows(words, "")
        self.assertEqual(rows[1][1], "Charges")
        self.assertEqual(rows[1][2], "17.70")

    def test_backup_contains_manifest_and_applies_retention(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            (root / "config" / "bank_templates").mkdir(parents=True)
            (root / "data" / "bank_converter.db").write_bytes(b"sqlite")
            (root / "config" / "settings.json").write_text("{}", encoding="utf-8")
            service = BackupService(root)
            first = service.create(keep=1)
            first.rename(first.with_name("bank_converter_backup_20000101_000000.zip"))
            latest = service.create(keep=1)
            self.assertEqual(len(list((root / "backups").glob("*.zip"))), 1)
            with zipfile.ZipFile(latest) as archive:
                self.assertIn("backup_manifest.json", archive.namelist())
                self.assertIn("data/bank_converter.db", archive.namelist())

    def test_logging_filter_redacts_account_and_upi(self) -> None:
        record = logging.LogRecord("test", logging.INFO, "", 0, "Account %s UPI demo.person@bank", ("123456789012",), None)
        SensitiveDataFilter().filter(record)
        rendered = record.getMessage()
        self.assertNotIn("123456789012", rendered)
        self.assertNotIn("demo.person@bank", rendered)

    def test_phase5_settings_have_safe_defaults(self) -> None:
        with TemporaryDirectory() as directory:
            settings = SettingsService(Path(directory) / "settings.json")
            values = settings.load()
            self.assertEqual(values["ocr_language"], "eng")
            self.assertFalse(values["automatic_backup"])
            self.assertEqual(values["logging_level"], "INFO")

    def test_source_runtime_paths_remain_in_workspace(self) -> None:
        with TemporaryDirectory() as directory, patch.object(sys, "frozen", False, create=True):
            root = Path(directory)
            paths = RuntimePaths.discover(root)
            paths.prepare()
            self.assertEqual(paths.data_root, root.resolve())
            self.assertTrue((root / "logs").is_dir())

    def test_frozen_runtime_refreshes_bundled_templates_only(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            resources = root / "resources"
            data = root / "data-root"
            bundled = resources / "config" / "bank_templates"
            installed = data / "config" / "bank_templates"
            bundled.mkdir(parents=True)
            installed.mkdir(parents=True)
            (bundled / "kotak.json").write_text('{"version": 2}', encoding="utf-8")
            (installed / "kotak.json").write_text('{"version": 1}', encoding="utf-8")
            (installed / "my_bank.json").write_text('{"custom": true}', encoding="utf-8")

            RuntimePaths(data, resources, True).prepare()

            self.assertEqual((installed / "kotak.json").read_text(encoding="utf-8"), '{"version": 2}')
            self.assertEqual((installed / "my_bank.json").read_text(encoding="utf-8"), '{"custom": true}')


if __name__ == "__main__":
    unittest.main()
