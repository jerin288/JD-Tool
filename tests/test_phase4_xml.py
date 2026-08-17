import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

from app.controllers.app_controller import AppController
from app.database.manager import DatabaseManager
from app.models.enums import DuplicateStatus, ImportStatus, ValidationStatus, VoucherType
from app.models.export import ExportGrouping, ExportOptions, ImportBatch, TallyImportResponse, VoucherMode
from app.models.matching_rule import MatchingRule
from app.models.tally import TallyLedger
from app.models.transaction import Transaction
from app.repositories.import_history_repository import ImportHistoryRepository
from app.repositories.matching_rule_repository import MatchingRuleRepository
from app.repositories.transaction_repository import TransactionRepository
from app.services.bank_template_service import BankTemplateService
from app.services.duplicate_detector import DuplicateDetector
from app.services.excel_exporter import ExcelExporter
from app.services.ledger_matcher import LedgerMatcher
from app.services.pdf_extractor import PdfExtractor
from app.services.transaction_parser import TransactionParser
from app.services.validation_service import ValidationService
from app.services.xml_exporter import TallyXmlExporter, XmlGenerationError


def voucher(
    voucher_type: VoucherType,
    amount: str,
    *,
    transaction_date: date = date(2026, 7, 1),
    row: int = 1,
    description: str = "Sample & Company <Test>",
) -> Transaction:
    debit = Decimal(amount) if voucher_type in {VoucherType.PAYMENT, VoucherType.CONTRA} else Decimal("0")
    credit = Decimal(amount) if voucher_type == VoucherType.RECEIPT else Decimal("0")
    return Transaction(
        transaction_date=transaction_date,
        row_number=row,
        description=description,
        narration=description,
        reference_number=f"REF-{row}",
        debit_amount=debit,
        credit_amount=credit,
        voucher_type=voucher_type,
        bank_ledger="Demo Bank A/c",
        opposite_ledger="Sample Ledger" if voucher_type != VoucherType.CONTRA else "Cash",
    )


class TallyXmlExporterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.exporter = TallyXmlExporter()
        self.options = ExportOptions("Demo Company")

    def _entry_amounts(self, item: Transaction, options: ExportOptions | None = None) -> dict[str, Decimal]:
        root = ET.fromstring(self.exporter.build_envelope([item], options or self.options))
        result: dict[str, Decimal] = {}
        for entry in root.findall(".//ALLLEDGERENTRIES.LIST"):
            result[entry.findtext("LEDGERNAME", "")] = Decimal(entry.findtext("AMOUNT", "0"))
        return result

    def _entry_details(self, item: Transaction) -> dict[str, tuple[Decimal, str]]:
        root = ET.fromstring(self.exporter.build_envelope([item], self.options))
        return {
            entry.findtext("LEDGERNAME", ""): (
                Decimal(entry.findtext("AMOUNT", "0")),
                entry.findtext("ISDEEMEDPOSITIVE", ""),
            )
            for entry in root.findall(".//ALLLEDGERENTRIES.LIST")
        }

    def test_payment_receipt_and_contra_follow_tally_debit_credit_direction(self) -> None:
        payment = self._entry_amounts(voucher(VoucherType.PAYMENT, "100.00"))
        receipt = self._entry_amounts(voucher(VoucherType.RECEIPT, "250.00"))
        contra_withdrawal = self._entry_amounts(voucher(VoucherType.CONTRA, "75.00"))
        contra_deposit_item = voucher(VoucherType.CONTRA, "80.00")
        contra_deposit_item.debit_amount = Decimal("0.00")
        contra_deposit_item.credit_amount = Decimal("80.00")
        contra_deposit = self._entry_amounts(contra_deposit_item)
        self.assertEqual(payment["Demo Bank A/c"], Decimal("100.00"))
        self.assertEqual(payment["Sample Ledger"], Decimal("-100.00"))
        self.assertEqual(receipt["Demo Bank A/c"], Decimal("-250.00"))
        self.assertEqual(receipt["Sample Ledger"], Decimal("250.00"))
        self.assertEqual(contra_withdrawal["Demo Bank A/c"], Decimal("75.00"))
        self.assertEqual(contra_withdrawal["Cash"], Decimal("-75.00"))
        self.assertEqual(contra_deposit["Demo Bank A/c"], Decimal("-80.00"))
        self.assertEqual(contra_deposit["Cash"], Decimal("80.00"))
        self.assertEqual(sum(payment.values()), Decimal("0.00"))
        self.assertEqual(sum(receipt.values()), Decimal("0.00"))
        self.assertEqual(sum(contra_withdrawal.values()), Decimal("0.00"))
        self.assertEqual(sum(contra_deposit.values()), Decimal("0.00"))

    def test_isdeemedpositive_matches_tally_negative_debit_convention(self) -> None:
        payment = self._entry_details(voucher(VoucherType.PAYMENT, "2000.00"))
        receipt = self._entry_details(voucher(VoucherType.RECEIPT, "18000.00"))
        self.assertEqual(payment["Sample Ledger"], (Decimal("-2000.00"), "Yes"))
        self.assertEqual(payment["Demo Bank A/c"], (Decimal("2000.00"), "No"))
        self.assertEqual(receipt["Demo Bank A/c"], (Decimal("-18000.00"), "Yes"))
        self.assertEqual(receipt["Sample Ledger"], (Decimal("18000.00"), "No"))

    def test_bank_charge_debits_expense_and_credits_bank(self) -> None:
        charge = voucher(VoucherType.PAYMENT, "17.70", description="Bank Charges")
        charge.opposite_ledger = "Bank Charges"
        details = self._entry_details(charge)
        self.assertEqual(details["Bank Charges"], (Decimal("-17.70"), "Yes"))
        self.assertEqual(details["Demo Bank A/c"], (Decimal("17.70"), "No"))

    def test_special_characters_are_escaped_and_bank_allocation_is_added(self) -> None:
        item = voucher(VoucherType.PAYMENT, "100.00")
        item.cheque_number = "CHQ-001"
        content = self.exporter.build_envelope([item], self.options)
        self.assertIn(b"Sample &amp; Company &lt;Test&gt;", content)
        root = ET.fromstring(content)
        self.assertEqual(root.findtext(".//NARRATION"), "Sample & Company <Test>")
        self.assertEqual(root.findtext(".//BANKALLOCATIONS.LIST/INSTRUMENTNUMBER"), "CHQ-001")
        self.assertEqual(root.findtext(".//BANKALLOCATIONS.LIST/TRANSACTIONTYPE"), "Cheque")

    def test_single_entry_mode_remains_balanced(self) -> None:
        options = ExportOptions("Demo Company", voucher_mode=VoucherMode.SINGLE_ENTRY)
        item = voucher(VoucherType.PAYMENT, "10.00")
        root = ET.fromstring(self.exporter.build_envelope([item], options))
        self.assertEqual(root.findtext(".//VCHENTRYMODE"), "Single Entry")
        amounts = [Decimal(node.text or "0") for node in root.findall(".//ALLLEDGERENTRIES.LIST/AMOUNT")]
        self.assertEqual(sum(amounts), Decimal("0.00"))
        self.assertEqual(len(amounts), 2)

    def test_invalid_voucher_is_blocked_but_duplicate_is_a_warning(self) -> None:
        zero = voucher(VoucherType.PAYMENT, "0.00")
        duplicate = voucher(VoucherType.PAYMENT, "20.00", row=2)
        duplicate.duplicate_status = DuplicateStatus.CONFIRMED_DUPLICATE
        report = self.exporter.validate([zero, duplicate], self.options)
        self.assertEqual(set(report.invalid_transaction_ids), {zero.id})
        self.assertIn(duplicate.id, report.valid_transaction_ids)
        self.assertTrue(
            any(issue.transaction_id == duplicate.id and issue.severity == "Warning" for issue in report.issues)
        )
        with self.assertRaises(XmlGenerationError):
            self.exporter.generate_documents([zero, duplicate], self.options)

    def test_unmatched_suspense_ledger_is_exportable_with_warning(self) -> None:
        item = voucher(VoucherType.PAYMENT, "20.00")
        item.opposite_ledger = "Suspense A/c"
        item.matching_confidence = Decimal("0")
        status, message = ValidationService().validate(item, require_ledgers=True)
        report = self.exporter.validate([item], self.options)
        self.assertEqual(status, ValidationStatus.WARNING)
        self.assertIn("Suspense", message)
        self.assertIn(item.id, report.valid_transaction_ids)
        self.assertFalse(report.invalid_transaction_ids)
        self.assertTrue(any(issue.transaction_id == item.id and issue.severity == "Warning" for issue in report.issues))

    def test_export_period_is_enforced(self) -> None:
        item = voucher(VoucherType.RECEIPT, "100.00", transaction_date=date(2026, 7, 1))
        options = ExportOptions("Demo Company", period_start=date(2026, 8, 1))
        report = self.exporter.validate([item], options)
        self.assertIn(item.id, report.invalid_transaction_ids)

    def test_grouping_by_voucher_type_and_month(self) -> None:
        items = [
            voucher(VoucherType.PAYMENT, "10", row=1, transaction_date=date(2026, 7, 1)),
            voucher(VoucherType.RECEIPT, "20", row=2, transaction_date=date(2026, 7, 2)),
            voucher(VoucherType.PAYMENT, "30", row=3, transaction_date=date(2026, 8, 1)),
        ]
        by_type, _ = self.exporter.generate_documents(
            items, ExportOptions("Demo Company", grouping=ExportGrouping.VOUCHER_TYPE)
        )
        by_month, _ = self.exporter.generate_documents(
            items, ExportOptions("Demo Company", grouping=ExportGrouping.MONTH)
        )
        self.assertEqual(
            {document.filename for document in by_type},
            {
                "tally_bank_vouchers_payment.xml",
                "tally_bank_vouchers_receipt.xml",
            },
        )
        self.assertEqual(
            {document.filename for document in by_month},
            {
                "tally_bank_vouchers_2026-07.xml",
                "tally_bank_vouchers_2026-08.xml",
            },
        )

    def test_atomic_file_export(self) -> None:
        with TemporaryDirectory() as directory:
            result = self.exporter.export(Path(directory), [voucher(VoucherType.PAYMENT, "50")], self.options)
            self.assertEqual(len(result.files), 1)
            self.assertTrue(result.files[0].exists())
            ET.parse(result.files[0])


class ImportHistoryRepositoryTests(unittest.TestCase):
    def test_import_batch_round_trip(self) -> None:
        with TemporaryDirectory() as directory:
            database = DatabaseManager(Path(directory) / "history.db")
            database.initialize()
            repository = ImportHistoryRepository(database)
            batch = ImportBatch(
                company_name="Demo Company",
                total_vouchers=3,
                created=2,
                failed=1,
                errors=1,
                messages=["BST-3: Invalid ledger"],
                created_at=datetime(2026, 8, 7, 12, 0),
            )
            repository.save(batch)
            loaded = repository.list_recent()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].created, 2)
            self.assertEqual(loaded[0].messages, ["BST-3: Invalid ledger"])

    def test_controller_records_per_voucher_import_status(self) -> None:
        class FakeImportClient:
            def __init__(self) -> None:
                self.responses = [
                    TallyImportResponse(created=1),
                    TallyImportResponse(errors=1, messages=("Invalid ledger",)),
                ]

            def import_vouchers(self, _payload: bytes) -> TallyImportResponse:
                return self.responses.pop(0)

        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = DatabaseManager(root / "controller.db")
            database.initialize()
            transaction_repository = TransactionRepository(database)
            history_repository = ImportHistoryRepository(database)
            controller = AppController(
                PdfExtractor(),
                TransactionParser(),
                transaction_repository,
                BankTemplateService(root / "templates"),
                DuplicateDetector(),
                ValidationService(),
                ExcelExporter(),
                MatchingRuleRepository(database),
                LedgerMatcher(),
                TallyXmlExporter(),
                history_repository,
            )
            controller.tally_client = FakeImportClient()  # type: ignore[assignment]
            session_id = transaction_repository.create_session(root / "sample.pdf", "Demo Bank")
            first = voucher(VoucherType.PAYMENT, "10", row=1)
            second = voucher(VoucherType.RECEIPT, "20", row=2)
            first.session_id = second.session_id = session_id
            controller.state.transactions = [first, second]
            batch = controller.import_xml_to_tally(ExportOptions("Demo Company"))
            self.assertEqual(first.import_status, ImportStatus.IMPORTED)
            self.assertEqual(second.import_status, ImportStatus.FAILED)
            self.assertEqual(batch.created, 1)
            self.assertEqual(batch.failed, 1)
            self.assertEqual(len(history_repository.list_recent()), 1)

    def test_controller_bulk_edit_and_selected_xml_export(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = DatabaseManager(root / "workspace.db")
            database.initialize()
            repository = TransactionRepository(database)
            controller = AppController(
                PdfExtractor(),
                TransactionParser(),
                repository,
                BankTemplateService(root / "templates"),
                DuplicateDetector(),
                ValidationService(),
                ExcelExporter(),
                MatchingRuleRepository(database),
                LedgerMatcher(),
                TallyXmlExporter(),
                ImportHistoryRepository(database),
            )
            session_id = repository.create_session(root / "sample.pdf", "Demo Bank")
            first = voucher(VoucherType.PAYMENT, "100", row=1)
            second = voucher(VoucherType.RECEIPT, "200", row=2)
            first.session_id = second.session_id = session_id
            controller.state.transactions = [first, second]
            repository.save_many([first, second])

            changed = controller.bulk_update_transactions(
                [first.id], ledger_name="Updated Supplier", voucher_type=VoucherType.PAYMENT
            )
            self.assertEqual(len(changed), 1)
            self.assertEqual(first.opposite_ledger, "Updated Supplier")
            self.assertEqual(first.matching_confidence, Decimal("100"))
            exported = controller.export_selected_xml(root / "exports", ExportOptions("Demo Company"), [first.id])
            self.assertEqual(exported.exported_transaction_ids, (first.id,))
            xml_root = ET.parse(exported.files[0]).getroot()
            self.assertEqual(len(xml_root.findall(".//VOUCHER")), 1)
            self.assertEqual(first.import_status, ImportStatus.EXPORTED)
            self.assertEqual(second.import_status, ImportStatus.NOT_EXPORTED)

    def test_saved_rules_store_and_apply_canonical_tally_ledger_names(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            database = DatabaseManager(root / "rules.db")
            database.initialize()
            repository = TransactionRepository(database)
            rule_repository = MatchingRuleRepository(database)
            controller = AppController(
                PdfExtractor(),
                TransactionParser(),
                repository,
                BankTemplateService(root / "templates"),
                DuplicateDetector(),
                ValidationService(),
                ExcelExporter(),
                rule_repository,
                LedgerMatcher(),
                TallyXmlExporter(),
                ImportHistoryRepository(database),
            )
            controller.state.tally_ledgers = [
                TallyLedger("SIB BANK", "Bank Accounts"),
                TallyLedger("DEMO ALUMINIUM AND PVC", "Sundry Creditors"),
                TallyLedger("EXAMPLE SUPPLIER", "Sundry Creditors"),
                TallyLedger("Suspense A/c", "Suspense A/c"),
            ]
            controller.save_matching_rule(
                MatchingRule("DEMO ALUMINIUM", "demo aluminium and pvc")
            )
            controller.save_matching_rule(MatchingRule("EX AMPLE SUPPLIER", "EXAMPLE SUPPLIER"))
            saved = {rule.pattern: rule.ledger_name for rule in rule_repository.list_all()}
            self.assertEqual(saved["DEMO ALUMINIUM"], "DEMO ALUMINIUM AND PVC")
            self.assertEqual(saved["EX AMPLE SUPPLIER"], "EXAMPLE SUPPLIER")

            item = voucher(
                VoucherType.PAYMENT,
                "2000",
                description="UPI/HDFC/123/DEMO ALUMINIUM AND PVC/reference",
            )
            item.session_id = repository.create_session(root / "statement.pdf", "Demo Bank")
            controller.state.transactions = [item]
            controller.apply_ledger_matching("SIB BANK")
            self.assertEqual(item.opposite_ledger, "DEMO ALUMINIUM AND PVC")
            self.assertEqual(item.matching_confidence, Decimal("100"))
            self.assertEqual(item.matching_method, "Saved Rule")

    def test_numeric_ledger_reference_is_blocked_from_xml(self) -> None:
        item = voucher(VoucherType.PAYMENT, "100")
        item.opposite_ledger = "169"
        report = TallyXmlExporter().validate([item], ExportOptions("Demo Company"))
        self.assertIn(item.id, report.invalid_transaction_ids)
        self.assertTrue(any("numeric index" in issue.message for issue in report.issues))


if __name__ == "__main__":
    unittest.main()
