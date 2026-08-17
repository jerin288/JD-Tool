"""Validated, balanced Tally Prime accounting voucher XML generation."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from app.models.enums import DuplicateStatus, ImportStatus, VoucherType
from app.models.export import (
    ExportGrouping,
    ExportOptions,
    ExportValidationReport,
    VoucherMode,
    VoucherValidationIssue,
    XmlDocument,
    XmlExportResult,
)
from app.models.transaction import Transaction
from app.services.validation_service import INVALID_XML_CHARACTERS
from app.utils.ledger_names import is_numeric_ledger_reference


class XmlGenerationError(RuntimeError):
    pass


class TallyXmlExporter:
    """Build Tally import envelopes while enforcing exact double-entry balance."""

    def validate(self, transactions: list[Transaction], options: ExportOptions) -> ExportValidationReport:
        issues: list[VoucherValidationIssue] = []
        valid_ids: list[str] = []
        invalid_ids: list[str] = []
        if not options.company_name.strip():
            for item in transactions:
                if not item.ignored:
                    issues.append(self._issue(item, "Error", "Tally company is not selected"))
                    invalid_ids.append(item.id)
            return ExportValidationReport(tuple(issues), (), tuple(dict.fromkeys(invalid_ids)))

        for item in transactions:
            if item.ignored:
                continue
            errors: list[str] = []
            warnings: list[str] = []
            if item.transaction_date is None:
                errors.append("Invalid or missing transaction date")
            elif (options.period_start and item.transaction_date < options.period_start) or (
                options.period_end and item.transaction_date > options.period_end
            ):
                errors.append("Transaction is outside the selected export period")
            if not item.debit_amount.is_finite() or not item.credit_amount.is_finite():
                errors.append("Amount is NaN or Infinity")
            elif item.debit_amount < 0 or item.credit_amount < 0:
                errors.append("A normalized debit or credit amount is negative")
            elif item.debit_amount and item.credit_amount:
                errors.append("Both debit and credit are entered")
            elif not item.debit_amount and not item.credit_amount:
                errors.append("Voucher amount is zero or missing")
            if not item.bank_ledger.strip():
                errors.append("Bank ledger is missing")
            elif is_numeric_ledger_reference(item.bank_ledger):
                errors.append("Bank ledger must be a Tally ledger name, not a numeric index")
            if not item.opposite_ledger.strip():
                errors.append("Opposite ledger is missing")
            elif is_numeric_ledger_reference(item.opposite_ledger):
                errors.append("Opposite ledger must be a Tally ledger name, not a numeric index")
            elif item.opposite_ledger.strip().casefold() == item.bank_ledger.strip().casefold():
                errors.append("Bank and opposite ledgers cannot be the same")
            if item.voucher_type not in {VoucherType.PAYMENT, VoucherType.RECEIPT, VoucherType.CONTRA}:
                errors.append("Voucher type is missing or unsupported")
            elif item.voucher_type == VoucherType.PAYMENT and not item.debit_amount:
                errors.append("Payment voucher must contain a debit/withdrawal")
            elif item.voucher_type == VoucherType.RECEIPT and not item.credit_amount:
                errors.append("Receipt voucher must contain a credit/deposit")
            if item.duplicate_status == DuplicateStatus.CONFIRMED_DUPLICATE:
                warnings.append("Confirmed duplicate has not been ignored or marked unique")
            elif item.duplicate_status == DuplicateStatus.SUSPECTED:
                warnings.append("Possible duplicate has not been confirmed")
            if item.matching_confidence == 0 or "suspense" in item.opposite_ledger.casefold():
                warnings.append("Unmatched ledger uses Suspense a/c")
            text_values = (item.description, item.narration, item.reference_number, item.cheque_number)
            if any(INVALID_XML_CHARACTERS.search(value) for value in text_values):
                errors.append("Contains an XML-forbidden control character")
            bank_amount, opposite_amount = self._signed_amounts(item)
            if bank_amount + opposite_amount != Decimal("0.00"):
                errors.append("Voucher debit and credit totals are unbalanced")
            if item.import_status == ImportStatus.IMPORTED:
                warnings.append("Voucher was previously imported")
            for message in errors:
                issues.append(self._issue(item, "Error", message))
            for message in warnings:
                issues.append(self._issue(item, "Warning", message))
            if errors:
                invalid_ids.append(item.id)
            else:
                valid_ids.append(item.id)
        return ExportValidationReport(tuple(issues), tuple(valid_ids), tuple(dict.fromkeys(invalid_ids)))

    def generate_documents(
        self, transactions: list[Transaction], options: ExportOptions
    ) -> tuple[tuple[XmlDocument, ...], ExportValidationReport]:
        report = self.validate(transactions, options)
        if report.invalid_transaction_ids:
            raise XmlGenerationError(
                f"XML generation blocked: {len(report.invalid_transaction_ids)} invalid transaction(s)."
            )
        valid_ids = set(report.valid_transaction_ids)
        valid = [item for item in transactions if item.id in valid_ids]
        if not valid:
            raise XmlGenerationError("There are no valid, non-ignored vouchers to export.")
        grouped: dict[str, list[Transaction]] = defaultdict(list)
        for item in valid:
            if options.grouping == ExportGrouping.VOUCHER_TYPE:
                key = item.voucher_type.value.lower()
            elif options.grouping == ExportGrouping.MONTH:
                assert item.transaction_date is not None
                key = item.transaction_date.strftime("%Y-%m")
            else:
                key = "combined"
            grouped[key].append(item)
        documents: list[XmlDocument] = []
        base = self._safe_filename(options.base_filename) or "tally_bank_vouchers"
        for key, items in sorted(grouped.items()):
            suffix = "" if key == "combined" else f"_{self._safe_filename(key)}"
            documents.append(
                XmlDocument(
                    filename=f"{base}{suffix}.xml",
                    content=self.build_envelope(items, options),
                    transaction_ids=tuple(item.id for item in items),
                )
            )
        return tuple(documents), report

    def export(
        self, output_directory: Path, transactions: list[Transaction], options: ExportOptions
    ) -> XmlExportResult:
        documents, report = self.generate_documents(transactions, options)
        output_directory.mkdir(parents=True, exist_ok=True)
        paths: list[Path] = []
        exported_ids: list[str] = []
        for document in documents:
            target = output_directory / document.filename
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(document.content)
            temporary.replace(target)
            paths.append(target)
            exported_ids.extend(document.transaction_ids)
        return XmlExportResult(tuple(paths), tuple(exported_ids), report)

    def build_envelope(self, transactions: list[Transaction], options: ExportOptions) -> bytes:
        envelope = ET.Element("ENVELOPE")
        header = ET.SubElement(envelope, "HEADER")
        ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
        body = ET.SubElement(envelope, "BODY")
        import_data = ET.SubElement(body, "IMPORTDATA")
        request_description = ET.SubElement(import_data, "REQUESTDESC")
        ET.SubElement(request_description, "REPORTNAME").text = "Vouchers"
        static = ET.SubElement(request_description, "STATICVARIABLES")
        ET.SubElement(static, "SVCURRENTCOMPANY").text = options.company_name
        request_data = ET.SubElement(import_data, "REQUESTDATA")
        for item in transactions:
            message = ET.SubElement(request_data, "TALLYMESSAGE", {"xmlns:UDF": "TallyUDF"})
            message.append(self._build_voucher(item, options))
        ET.indent(envelope, space="  ")
        return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)

    def _build_voucher(self, item: Transaction, options: ExportOptions) -> ET.Element:
        assert item.transaction_date is not None
        voucher = ET.Element(
            "VOUCHER",
            {
                "VCHTYPE": item.voucher_type.value,
                "ACTION": "Create",
                "OBJVIEW": "Accounting Voucher View",
            },
        )
        date_text = item.transaction_date.strftime("%Y%m%d")
        voucher_number = item.tally_voucher_number.strip() or self._voucher_number(item)
        item.tally_voucher_number = voucher_number
        self._text(voucher, "DATE", date_text)
        self._text(voucher, "EFFECTIVEDATE", date_text)
        self._text(voucher, "VOUCHERNUMBER", voucher_number)
        self._text(voucher, "NARRATION", item.narration or item.description)
        self._text(voucher, "VOUCHERTYPENAME", item.voucher_type.value)
        self._text(voucher, "PARTYLEDGERNAME", item.opposite_ledger)
        self._text(voucher, "PERSISTEDVIEW", "Accounting Voucher View")
        entry_mode = (
            "Single Entry"
            if options.voucher_mode == VoucherMode.SINGLE_ENTRY
            and item.voucher_type in {VoucherType.PAYMENT, VoucherType.RECEIPT}
            else "Double Entry"
        )
        self._text(voucher, "VCHENTRYMODE", entry_mode)
        self._text(voucher, "ISINVOICE", "No")
        self._text(voucher, "ISOPTIONAL", "No")
        bank_amount, opposite_amount = self._signed_amounts(item)
        self._append_ledger_entry(voucher, item.opposite_ledger, opposite_amount)
        self._append_ledger_entry(
            voucher,
            item.bank_ledger,
            bank_amount,
            transaction=item if options.include_bank_allocations else None,
        )
        return voucher

    def _append_ledger_entry(
        self,
        voucher: ET.Element,
        ledger_name: str,
        amount: Decimal,
        transaction: Transaction | None = None,
    ) -> None:
        entry = ET.SubElement(voucher, "ALLLEDGERENTRIES.LIST")
        self._text(entry, "LEDGERNAME", ledger_name)
        self._text(entry, "ISDEEMEDPOSITIVE", "Yes" if amount < 0 else "No")
        self._text(entry, "LEDGERFROMITEM", "No")
        self._text(entry, "REMOVEZEROENTRIES", "No")
        self._text(entry, "ISPARTYLEDGER", "Yes" if transaction is None else "No")
        self._text(entry, "AMOUNT", self._format_amount(amount))
        if transaction is not None and (transaction.reference_number or transaction.cheque_number):
            allocation = ET.SubElement(entry, "BANKALLOCATIONS.LIST")
            self._text(allocation, "DATE", transaction.transaction_date.strftime("%Y%m%d"))
            self._text(allocation, "INSTRUMENTDATE", transaction.transaction_date.strftime("%Y%m%d"))
            self._text(allocation, "NAME", transaction.reference_number or transaction.cheque_number)
            self._text(allocation, "TRANSACTIONTYPE", self._transaction_type(transaction))
            self._text(allocation, "INSTRUMENTNUMBER", transaction.cheque_number or transaction.reference_number)
            self._text(allocation, "UNIQUEREFERENCENUMBER", transaction.reference_number)
            self._text(allocation, "STATUS", "No")
            self._text(allocation, "AMOUNT", self._format_amount(amount))

    @staticmethod
    def _signed_amounts(item: Transaction) -> tuple[Decimal, Decimal]:
        """Return bank/opposite amounts using Tally's negative-debit convention."""
        if item.debit_amount:
            # A bank-statement withdrawal credits the bank and debits the counter-ledger.
            return abs(item.debit_amount), -abs(item.debit_amount)
        if item.credit_amount:
            # A bank-statement deposit debits the bank and credits the counter-ledger.
            return -abs(item.credit_amount), abs(item.credit_amount)
        return Decimal("0.00"), Decimal("0.00")

    @staticmethod
    def _format_amount(amount: Decimal) -> str:
        if not amount.is_finite():
            raise XmlGenerationError("NaN and Infinity amounts cannot be exported.")
        return f"{amount.quantize(Decimal('0.01')):.2f}"

    @staticmethod
    def _transaction_type(item: Transaction) -> str:
        if item.cheque_number:
            return "Cheque"
        description = item.description.upper()
        for name in ("UPI", "NEFT", "IMPS", "RTGS"):
            if name in description:
                return name
        return "Others"

    @staticmethod
    def _voucher_number(item: Transaction) -> str:
        assert item.transaction_date is not None
        suffix = f"{item.row_number:05d}" if item.row_number else item.id.split("-")[0].upper()
        return f"BST-{item.transaction_date:%Y%m%d}-{suffix}"

    @staticmethod
    def _safe_filename(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._")

    @staticmethod
    def _text(parent: ET.Element, tag: str, value: str) -> ET.Element:
        element = ET.SubElement(parent, tag)
        element.text = value
        return element

    @staticmethod
    def _issue(item: Transaction, severity: str, message: str) -> VoucherValidationIssue:
        return VoucherValidationIssue(item.id, item.row_number, severity, message)
