"""Orchestrates application workflows without coupling services to Tk widgets."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from app.models.bank_template import BankTemplate
from app.models.enums import DuplicateStatus, ImportStatus, ValidationStatus, VoucherType
from app.models.export import (
    ExportOptions,
    ExportValidationReport,
    ImportBatch,
    XmlExportResult,
)
from app.models.mapping import ColumnMapping
from app.models.matching_rule import MatchingRule
from app.models.tally import TallyCompany, TallyCompanyData, TallyConnectionResult, TallyLedger
from app.models.transaction import Transaction
from app.repositories.import_history_repository import ImportHistoryRepository
from app.repositories.matching_rule_repository import MatchingRuleRepository
from app.repositories.transaction_repository import TransactionRepository
from app.services.bank_template_service import BankTemplateService
from app.services.duplicate_detector import DuplicateDetector, DuplicateMatch
from app.services.excel_exporter import ExcelExporter
from app.services.ledger_matcher import LedgerMatcher
from app.services.pdf_extractor import PdfExtractionResult, PdfExtractor
from app.services.tally_client import TallyClient, TallyConnectionError
from app.services.transaction_parser import TransactionParser
from app.services.validation_service import ValidationService, ValidationSummary
from app.services.xml_exporter import TallyXmlExporter, XmlGenerationError
from app.utils.ledger_names import canonical_ledger_name, is_numeric_ledger_reference


@dataclass(slots=True)
class ApplicationState:
    selected_pdf: Path | None = None
    selected_bank: str = "Automatic"
    extraction: PdfExtractionResult | None = None
    mapping: ColumnMapping = field(default_factory=ColumnMapping)
    session_id: str = ""
    transactions: list[Transaction] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    bank_template: BankTemplate | None = None
    duplicate_matches: list[DuplicateMatch] = field(default_factory=list)
    validation_summary: ValidationSummary | None = None
    tally_server_url: str = "http://localhost:9000"
    tally_companies: list[TallyCompany] = field(default_factory=list)
    selected_company: TallyCompany | None = None
    tally_ledgers: list[TallyLedger] = field(default_factory=list)
    tally_voucher_types: list[str] = field(default_factory=list)
    selected_bank_ledger: str = ""
    last_import_batch: ImportBatch | None = None
    last_export_validation: ExportValidationReport | None = None


class AppController:
    """Coordinates extraction, parsing, editing, and persistence."""

    def __init__(
        self,
        extractor: PdfExtractor,
        parser: TransactionParser,
        repository: TransactionRepository,
        templates: BankTemplateService,
        duplicate_detector: DuplicateDetector,
        validator: ValidationService,
        excel_exporter: ExcelExporter,
        rule_repository: MatchingRuleRepository,
        ledger_matcher: LedgerMatcher,
        xml_exporter: TallyXmlExporter,
        import_history: ImportHistoryRepository,
        tally_client_factory: Callable[[str], TallyClient] = TallyClient,
    ) -> None:
        self.extractor = extractor
        self.parser = parser
        self.repository = repository
        self.templates = templates
        self.duplicate_detector = duplicate_detector
        self.validator = validator
        self.excel_exporter = excel_exporter
        self.rule_repository = rule_repository
        self.ledger_matcher = ledger_matcher
        self.xml_exporter = xml_exporter
        self.import_history = import_history
        self.tally_client_factory = tally_client_factory
        self.tally_client: TallyClient | None = None
        self.state = ApplicationState()
        self.on_state_changed: Callable[[], None] = lambda: None

    def extract_pdf(
        self,
        path: Path,
        bank_name: str,
        password: str = "",
        progress: Callable[[int, int, str], None] | None = None,
    ) -> PdfExtractionResult:
        result = self.extractor.extract(path, password, progress)
        self.state.selected_pdf = path
        self.state.selected_bank = bank_name
        self.state.extraction = result
        statement_text = "\n".join(page.text for page in result.pages)
        template = (
            self.templates.detect(statement_text) if bank_name == "Automatic" else self.templates.get_by_bank(bank_name)
        )
        self.state.bank_template = template
        if template and bank_name == "Automatic":
            self.state.selected_bank = template.bank_name
        self.state.mapping = self.parser.suggest_mapping(result.rows, template)
        self.state.warnings = list(result.warnings)
        return result

    def parse_transactions(self, mapping: ColumnMapping) -> tuple[list[Transaction], list[str]]:
        if self.state.extraction is None or self.state.selected_pdf is None:
            raise RuntimeError("Extract a PDF before mapping columns.")
        transactions, warnings = self.parser.parse(self.state.extraction.rows, mapping, self.state.bank_template)
        if not transactions:
            raise ValueError("No transactions matched this mapping. Review the header row and columns.")
        session_id = self.repository.create_session(self.state.selected_pdf, self.state.selected_bank)
        for transaction in transactions:
            transaction.session_id = session_id
        self.state.mapping = mapping
        self.state.session_id = session_id
        self.state.transactions = transactions
        self.state.warnings = [*self.state.extraction.warnings, *warnings]
        self.state.duplicate_matches = self.duplicate_detector.detect(transactions)
        self.state.validation_summary = self.validator.validate_all(transactions)
        if self.state.tally_ledgers and self.state.selected_bank_ledger:
            self._apply_ledger_matches(transactions, self.state.selected_bank_ledger, 78, "Suspense A/c")
            self.state.validation_summary = self.validator.validate_all(transactions, require_ledgers=True)
        self.repository.save_many(transactions)
        self.on_state_changed()
        return transactions, warnings

    def save_transaction(self, transaction: Transaction) -> None:
        self._canonicalize_transaction_ledger(transaction)
        status, message = self.validator.validate(transaction, require_ledgers=bool(self.state.selected_bank_ledger))
        transaction.validation_status = status
        transaction.validation_message = message
        self.repository.save(transaction)
        self.on_state_changed()

    def save_transactions(self, transactions: list[Transaction]) -> None:
        """Validate and persist a UI batch in one database transaction."""
        for transaction in transactions:
            self._canonicalize_transaction_ledger(transaction)
            status, message = self.validator.validate(
                transaction, require_ledgers=bool(self.state.selected_bank_ledger)
            )
            transaction.validation_status = status
            transaction.validation_message = message
        self.repository.save_many(transactions)
        self.on_state_changed()

    def bulk_update_transactions(
        self,
        transaction_ids: list[str],
        *,
        ledger_name: str | None = None,
        voucher_type: VoucherType | None = None,
        ignored: bool | None = None,
    ) -> list[Transaction]:
        selected = set(transaction_ids)
        changed = [item for item in self.state.transactions if item.id in selected]
        canonical = None
        if ledger_name is not None:
            if is_numeric_ledger_reference(ledger_name):
                raise ValueError("A numeric ledger index is invalid. Select the actual Tally ledger name.")
            canonical = ledger_name.strip()
            if self.state.tally_ledgers:
                canonical = canonical_ledger_name(
                    ledger_name, (item.name for item in self.state.tally_ledgers)
                )
        for item in changed:
            if ledger_name is not None:
                item.opposite_ledger = canonical or ""
                item.matching_confidence = Decimal("100") if canonical else Decimal("0")
                item.matching_method = "Manual" if canonical else ""
            if voucher_type is not None:
                item.voucher_type = voucher_type
            if ignored is not None:
                item.ignored = ignored
        self.save_transactions(changed)
        return changed

    def mark_transactions_valid(self, transaction_ids: list[str]) -> list[Transaction]:
        """Record an explicit review acknowledgement without bypassing XML validation."""
        selected = set(transaction_ids)
        changed = [item for item in self.state.transactions if item.id in selected]
        for item in changed:
            item.validation_status = ValidationStatus.VALID
            item.validation_message = "Marked valid after manual review"
        self.repository.save_many(changed)
        self.on_state_changed()
        return changed

    def analyze_transactions(self, duplicate_threshold: int = 75) -> tuple[list[DuplicateMatch], ValidationSummary]:
        matches = self.duplicate_detector.detect(self.state.transactions, duplicate_threshold)
        summary = self.validator.validate_all(self.state.transactions)
        self.repository.save_many(self.state.transactions)
        self.state.duplicate_matches = matches
        self.state.validation_summary = summary
        self.on_state_changed()
        return matches, summary

    def set_duplicate_status(self, transaction_ids: list[str], status: DuplicateStatus) -> None:
        selected = set(transaction_ids)
        for item in self.state.transactions:
            if item.id in selected:
                item.duplicate_status = status
                if status in {DuplicateStatus.NONE, DuplicateStatus.CONFIRMED_UNIQUE}:
                    item.duplicate_of = ""
        self.state.validation_summary = self.validator.validate_all(self.state.transactions)
        self.repository.save_many([item for item in self.state.transactions if item.id in selected])
        self.on_state_changed()

    def set_ignored(self, transaction_ids: list[str], ignored: bool) -> None:
        selected = set(transaction_ids)
        changed = [item for item in self.state.transactions if item.id in selected]
        for item in changed:
            item.ignored = ignored
            status, message = self.validator.validate(item)
            item.validation_status, item.validation_message = status, message
        self.repository.save_many(changed)
        self.on_state_changed()

    def export_excel(self, path: Path, duplicate_threshold: int = 75) -> Path:
        self.state.duplicate_matches = self.duplicate_detector.detect(self.state.transactions, duplicate_threshold)
        self.state.validation_summary = self.validator.validate_all(self.state.transactions)
        self.repository.save_many(self.state.transactions)
        source = self.state.selected_pdf.name if self.state.selected_pdf else ""
        return self.excel_exporter.export(path, self.state.transactions, source)

    def save_current_template(self, bank_name: str, mapping: ColumnMapping) -> BankTemplate:
        template = self.templates.save_mapping(bank_name, mapping)
        self.state.bank_template = template
        self.state.selected_bank = template.bank_name
        self.on_state_changed()
        return template

    def apply_template(self, template_id: str) -> ColumnMapping:
        template = next((item for item in self.templates.list_templates() if item.template_id == template_id), None)
        if template is None:
            raise ValueError("The selected bank template no longer exists.")
        if self.state.extraction is None:
            raise RuntimeError("Extract a PDF before applying a template.")
        self.state.bank_template = template
        self.state.selected_bank = template.bank_name
        self.state.mapping = self.parser.suggest_mapping(self.state.extraction.rows, template)
        self.on_state_changed()
        return self.state.mapping

    def test_tally_connection(self, server_url: str) -> TallyConnectionResult:
        client = self.tally_client_factory(server_url)
        result = client.test_connection()
        self.tally_client = client
        self.state.tally_server_url = result.server_url
        self.state.tally_companies = list(result.companies)
        return result

    def load_tally_company(self, company_name: str) -> TallyCompanyData:
        company = next(
            (item for item in self.state.tally_companies if item.name == company_name),
            TallyCompany(company_name),
        )
        client = self.tally_client or self.tally_client_factory(self.state.tally_server_url)
        data = client.fetch_company_data(company)
        self.tally_client = client
        self.state.selected_company = data.company
        self.state.tally_ledgers = list(data.ledgers)
        self.state.tally_voucher_types = list(data.voucher_types)
        return data

    def create_tally_ledger(self, ledger_name: str, parent_group: str) -> TallyCompanyData:
        selected_company = self.state.selected_company
        if selected_company is None:
            raise RuntimeError("Select and load a Tally company first.")
        ledger_name = ledger_name.strip()
        parent_group = parent_group.strip()
        if not ledger_name:
            raise ValueError("Enter a ledger name.")
        if not parent_group:
            raise ValueError("Enter a parent group.")
        client = self.tally_client or self.tally_client_factory(self.state.tally_server_url)
        client.create_ledger(selected_company.name, ledger_name, parent_group)
        self.tally_client = client
        return self.load_tally_company(selected_company.name)

    def apply_ledger_matching(
        self,
        bank_ledger_name: str,
        fuzzy_threshold: int = 78,
        suspense_ledger: str = "Suspense A/c",
    ) -> dict[str, int]:
        if not self.state.tally_ledgers:
            raise RuntimeError("Download ledgers from an open Tally company first.")
        if not bank_ledger_name.strip():
            raise ValueError("Select the bank ledger used by this statement.")
        canonical_bank = canonical_ledger_name(bank_ledger_name, (item.name for item in self.state.tally_ledgers))
        self.state.selected_bank_ledger = canonical_bank
        counts = self._apply_ledger_matches(self.state.transactions, canonical_bank, fuzzy_threshold, suspense_ledger)
        self.state.validation_summary = self.validator.validate_all(self.state.transactions, require_ledgers=True)
        self.repository.save_many(self.state.transactions)
        return counts

    def _apply_ledger_matches(
        self,
        transactions: list[Transaction],
        bank_ledger_name: str,
        fuzzy_threshold: int,
        suspense_ledger: str,
    ) -> dict[str, int]:
        rules = self.rule_repository.list_enabled()
        counts = self.ledger_matcher.apply(
            transactions,
            self.state.tally_ledgers,
            rules,
            bank_ledger_name,
            fuzzy_threshold,
            suspense_ledger,
        )
        rule_uses = Counter(item.matching_rule_id for item in transactions if item.matching_rule_id)
        for rule_id, count in rule_uses.items():
            self.rule_repository.increment_use(rule_id, count)
        return counts

    def list_matching_rules(self) -> list[MatchingRule]:
        return self.rule_repository.list_all()

    def save_matching_rule(self, rule: MatchingRule) -> None:
        if rule.ledger_name == "Download Tally ledgers first":
            raise ValueError("Download ledgers and select a real Tally ledger first.")
        if not self.state.tally_ledgers:
            raise ValueError("Download Tally ledgers before saving a rule.")
        rule.pattern = rule.pattern.strip()
        rule.ledger_name = canonical_ledger_name(
            rule.ledger_name, (item.name for item in self.state.tally_ledgers)
        )
        rule.legacy_ledger_reference = ""
        self.rule_repository.save(rule)
        self.on_state_changed()

    def _canonicalize_transaction_ledger(self, transaction: Transaction) -> None:
        """Keep UI indices out of the transaction model and preserve Tally spelling."""

        if not transaction.opposite_ledger:
            return
        if is_numeric_ledger_reference(transaction.opposite_ledger):
            raise ValueError("A numeric ledger index is invalid. Select the actual Tally ledger name.")
        if self.state.tally_ledgers:
            transaction.opposite_ledger = canonical_ledger_name(
                transaction.opposite_ledger, (item.name for item in self.state.tally_ledgers)
            )

    def delete_matching_rule(self, rule_id: str) -> None:
        self.rule_repository.delete(rule_id)
        self.on_state_changed()

    def validate_xml_export(self, options: ExportOptions, failed_only: bool = False) -> ExportValidationReport:
        transactions = self._export_transactions(failed_only)
        report = self.xml_exporter.validate(transactions, options)
        self.state.last_export_validation = report
        return report

    def preview_xml(self, options: ExportOptions, failed_only: bool = False) -> tuple[str, ExportValidationReport]:
        transactions = self._export_transactions(failed_only)
        report = self.xml_exporter.validate(transactions, options)
        self.state.last_export_validation = report
        valid_ids = set(report.valid_transaction_ids)
        eligible = [item for item in transactions if item.id in valid_ids]
        documents = self.xml_exporter.generate_documents(eligible, options)[0] if eligible else ()
        error_count = sum(issue.severity.casefold() == "error" for issue in report.issues)
        warning_count = sum(issue.severity.casefold() == "warning" for issue in report.issues)
        notice = (
            f"<!-- Preview validation: {error_count} critical error(s), {warning_count} warning(s). "
            "Invalid transactions are omitted from the XML below. -->"
        )
        document_text = "\n\n".join(
            f"<!-- {document.filename} -->\n{document.content.decode('utf-8')}" for document in documents
        )
        preview = f"{notice}\n\n{document_text}" if document_text else notice
        return preview, report

    def get_critical_error_count(self, transactions: list[Transaction] | None = None) -> int:
        """Count only technical voucher errors; matching warnings remain exportable."""

        items = transactions if transactions is not None else self.state.transactions
        return sum(
            self.validator.validate(item, require_ledgers=True)[0] == ValidationStatus.INVALID
            for item in items
            if not item.ignored
        )

    def export_xml(self, output_directory: Path, options: ExportOptions, failed_only: bool = False) -> XmlExportResult:
        result = self.xml_exporter.export(output_directory, self._export_transactions(failed_only), options)
        exported = set(result.exported_transaction_ids)
        changed = [item for item in self.state.transactions if item.id in exported]
        for item in changed:
            if item.import_status != ImportStatus.IMPORTED:
                item.import_status = ImportStatus.EXPORTED
                item.import_message = "XML exported"
        self.repository.save_many(changed)
        self.state.last_export_validation = result.validation
        return result

    def export_selected_xml(
        self,
        output_directory: Path,
        options: ExportOptions,
        transaction_ids: list[str],
    ) -> XmlExportResult:
        selected = set(transaction_ids)
        transactions = [item for item in self.state.transactions if item.id in selected and not item.ignored]
        if not transactions:
            raise XmlGenerationError("Select at least one non-ignored transaction to export.")
        result = self.xml_exporter.export(output_directory, transactions, options)
        exported = set(result.exported_transaction_ids)
        changed = [item for item in transactions if item.id in exported]
        for item in changed:
            if item.import_status != ImportStatus.IMPORTED:
                item.import_status = ImportStatus.EXPORTED
                item.import_message = "Selected XML exported"
        self.repository.save_many(changed)
        self.state.last_export_validation = result.validation
        return result

    def import_xml_to_tally(
        self,
        options: ExportOptions,
        failed_only: bool = False,
        progress: Callable[[int, int, str], None] | None = None,
    ) -> ImportBatch:
        transactions = [
            item for item in self._export_transactions(failed_only) if item.import_status != ImportStatus.IMPORTED
        ]
        report = self.xml_exporter.validate(transactions, options)
        self.state.last_export_validation = report
        if report.invalid_transaction_ids:
            raise XmlGenerationError(
                f"Tally import blocked: {len(report.invalid_transaction_ids)} invalid transaction(s)."
            )
        valid_ids = set(report.valid_transaction_ids)
        eligible = [item for item in transactions if item.id in valid_ids]
        if not eligible:
            raise XmlGenerationError("There are no valid vouchers to import.")
        client = self.tally_client or self.tally_client_factory(self.state.tally_server_url)
        batch = ImportBatch(options.company_name, len(eligible))
        for index, item in enumerate(eligible, start=1):
            if progress:
                progress(index - 1, len(eligible), item.tally_voucher_number or item.description)
            try:
                payload = self.xml_exporter.build_envelope([item], options)
                response = client.import_vouchers(payload)
                batch.created += response.created
                batch.altered += response.altered
                batch.ignored += response.ignored + response.cancelled
                batch.errors += response.errors + response.exceptions
                messages = list(response.messages)
                if response.succeeded and (response.created or response.altered):
                    item.import_status = ImportStatus.IMPORTED
                    item.import_message = "; ".join(messages) or "Imported successfully"
                    item.imported_at = datetime.now()
                else:
                    item.import_status = ImportStatus.FAILED
                    item.import_message = "; ".join(messages) or "Tally ignored or did not create the voucher"
                    batch.failed += 1
                    batch.messages.append(f"{item.tally_voucher_number}: {item.import_message}")
            except TallyConnectionError as exc:
                item.import_status = ImportStatus.FAILED
                item.import_message = str(exc)
                batch.failed += 1
                batch.errors += 1
                batch.messages.append(f"{item.tally_voucher_number}: {exc}")
                remaining = eligible[index:]
                for pending in remaining:
                    pending.import_status = ImportStatus.FAILED
                    pending.import_message = f"Import stopped: {exc}"
                    batch.failed += 1
                break
        if progress:
            progress(len(eligible), len(eligible), "Complete")
        self.repository.save_many(eligible)
        self.import_history.save(batch)
        self.state.last_import_batch = batch
        return batch

    def list_import_history(self, limit: int = 100) -> list[ImportBatch]:
        return self.import_history.list_recent(limit)

    def _export_transactions(self, failed_only: bool) -> list[Transaction]:
        if failed_only:
            return [
                item
                for item in self.state.transactions
                if item.import_status == ImportStatus.FAILED and not item.ignored
            ]
        return [item for item in self.state.transactions if not item.ignored]

    def delete_transactions(self, transaction_ids: list[str]) -> None:
        self.repository.delete_many(transaction_ids)
        selected = set(transaction_ids)
        self.state.transactions = [item for item in self.state.transactions if item.id not in selected]
        self.on_state_changed()

    def duplicate_transactions(self, transaction_ids: list[str]) -> list[Transaction]:
        selected = set(transaction_ids)
        clones = [item.clone() for item in self.state.transactions if item.id in selected]
        for clone in clones:
            clone.row_number = len(self.state.transactions) + 1
            self.state.transactions.append(clone)
        self.repository.save_many(clones)
        self.on_state_changed()
        return clones
