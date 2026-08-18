import unittest
import xml.etree.ElementTree as ET
from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import requests

from app.database.manager import DatabaseManager
from app.models.enums import RuleMatchType, VoucherType
from app.models.matching_rule import MatchingRule
from app.models.tally import TallyLedger
from app.models.transaction import Transaction
from app.repositories.matching_rule_repository import MatchingRuleRepository
from app.services.ledger_matcher import LedgerMatcher
from app.services.tally_client import (
    TallyClient,
    TallyInvalidResponseError,
    TallyLedgerCreationError,
    TallyNotRunningError,
)
from app.services.voucher_type_detector import VoucherTypeDetector

COMPANY_XML = b"""
<ENVELOPE><BODY><DATA><COLLECTION>
  <COMPANY>0</COMPANY>
  <COMPANY NAME="Demo Company"><GUID>C-1</GUID><STARTINGFROM>20260401</STARTINGFROM></COMPANY>
  <COMPANY NAME="Second Company"><GUID>C-2</GUID></COMPANY>
</COLLECTION></DATA></BODY></ENVELOPE>
"""

LEDGER_XML = b"""
<ENVELOPE><BODY><DATA><COLLECTION>
  <LEDGER>4</LEDGER>
  <LEDGER NAME="Demo Bank A/c"><PARENT>Bank Accounts</PARENT><GUID>L-1</GUID></LEDGER>
  <LEDGER NAME="Demo Traders"><PARENT>Sundry Creditors</PARENT><GUID>L-2</GUID></LEDGER>
  <LEDGER NAME="Cash"><PARENT>Cash-in-Hand</PARENT><GUID>L-3</GUID></LEDGER>
  <LEDGER NAME="Suspense A/c"><PARENT>Suspense A/c</PARENT><GUID>L-4</GUID></LEDGER>
</COLLECTION></DATA></BODY></ENVELOPE>
"""

VOUCHER_XML = b"""
<ENVELOPE><BODY><DATA><COLLECTION>
  <VOUCHERTYPE>3</VOUCHERTYPE>
  <VOUCHERTYPE NAME="Payment"/><VOUCHERTYPE NAME="Receipt"/><VOUCHERTYPE NAME="Contra"/>
</COLLECTION></DATA></BODY></ENVELOPE>
"""

IMPORT_RESPONSE_XML = b"""
<RESPONSE>
  <CREATED>1</CREATED><ALTERED>0</ALTERED><IGNORED>0</IGNORED><ERRORS>0</ERRORS>
  <CANCELLED>0</CANCELLED><EXCEPTIONS>0</EXCEPTIONS><LASTVCHID>42</LASTVCHID>
</RESPONSE>
"""

CREATE_LEDGER_RESPONSE_XML = b"""
<RESPONSE><CREATED>1</CREATED><ALTERED>0</ALTERED><ERRORS>0</ERRORS></RESPONSE>
"""

CREATE_LEDGER_ERROR_XML = b"""
<RESPONSE><CREATED>0</CREATED><ERRORS>1</ERRORS><LINEERROR>Duplicate ledger name</LINEERROR></RESPONSE>
"""


class FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code
        self.text = content.decode("utf-8", errors="replace")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, responses: list[bytes] | None = None, error: Exception | None = None) -> None:
        self.responses = list(responses or [])
        self.error = error
        self.payloads: list[bytes] = []

    def post(self, _url: str, **kwargs: object) -> FakeResponse:
        if self.error:
            raise self.error
        self.payloads.append(kwargs["data"])  # type: ignore[arg-type]
        return FakeResponse(self.responses.pop(0))


def payment(description: str = "UPI/DEMO TRADERS/123456789012") -> Transaction:
    return Transaction(
        transaction_date=date(2026, 7, 1), description=description,
        debit_amount=Decimal("100.00"), voucher_type=VoucherType.PAYMENT,
    )


class TallyClientTests(unittest.TestCase):
    def test_companies_ledgers_and_voucher_types_are_parsed(self) -> None:
        session = FakeSession([COMPANY_XML, LEDGER_XML, VOUCHER_XML])
        client = TallyClient("localhost:9000", session=session)
        result = client.test_connection()
        self.assertEqual([item.name for item in result.companies], ["Demo Company", "Second Company"])
        data = client.fetch_company_data(result.companies[0])
        self.assertEqual(data.company.name, "Demo Company")
        self.assertEqual(len(data.ledgers), 4)
        self.assertEqual(data.voucher_types, ("Contra", "Payment", "Receipt"))
        self.assertIn(b"SVCURRENTCOMPANY", session.payloads[1])
        self.assertIn(b"Demo Company", session.payloads[1])

    def test_invalid_xml_is_reported(self) -> None:
        client = TallyClient(session=FakeSession([b"not xml"]))
        with self.assertRaises(TallyInvalidResponseError):
            client.test_connection()

    def test_invalid_tally_character_references_are_repaired(self) -> None:
        malformed_ledgers = LEDGER_XML.replace(
            b"Demo Traders", b"Demo&#4;Traders"
        ).replace(b"Cash-in-Hand", b"Cash-in-\x0bHand")
        session = FakeSession([COMPANY_XML, malformed_ledgers, VOUCHER_XML])
        client = TallyClient(session=session)
        company = client.test_connection().companies[0]
        data = client.fetch_company_data(company)
        by_name = {item.name: item for item in data.ledgers}
        self.assertIn("Demo Traders", by_name)
        self.assertEqual(by_name["Cash"].parent_group, "Cash-in- Hand")

    def test_valid_numeric_character_references_are_preserved(self) -> None:
        payload = b'<ENVELOPE><LEDGER NAME="A&#38;B"/></ENVELOPE>'
        repaired, count = TallyClient._sanitize_xml_payload(payload)
        self.assertEqual(repaired, payload)
        self.assertEqual(count, 0)

    def test_connection_refusal_is_user_friendly(self) -> None:
        client = TallyClient(session=FakeSession(error=requests.ConnectionError("refused")))
        with self.assertRaises(TallyNotRunningError):
            client.test_connection()

    def test_external_tally_urls_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            TallyClient("https://example.com:9000")

    def test_import_response_counts_are_parsed(self) -> None:
        client = TallyClient(session=FakeSession([IMPORT_RESPONSE_XML]))
        response = client.import_vouchers(b"<ENVELOPE/>")
        self.assertEqual(response.created, 1)
        self.assertEqual(response.last_voucher_id, "42")
        self.assertTrue(response.succeeded)

    def test_import_line_error_is_returned_in_report(self) -> None:
        payload = b"""
        <RESPONSE><CREATED>0</CREATED><IGNORED>0</IGNORED><ERRORS>1</ERRORS>
        <LINEERROR>Ledger does not exist</LINEERROR></RESPONSE>
        """
        response = TallyClient(session=FakeSession([payload])).import_vouchers(b"<ENVELOPE/>")
        self.assertFalse(response.succeeded)
        self.assertEqual(response.messages, ("Ledger does not exist",))

    def test_create_ledger_payload_uses_all_masters_import(self) -> None:
        session = FakeSession([CREATE_LEDGER_RESPONSE_XML])
        client = TallyClient(session=session)
        result = client.create_ledger("Demo Company", "New Supplier", "Sundry Creditors")
        self.assertTrue(result.succeeded)
        self.assertEqual(result.created, 1)
        root = ET.fromstring(session.payloads[0])
        self.assertEqual(root.findtext("./HEADER/TALLYREQUEST"), "Import Data")
        self.assertEqual(root.findtext("./BODY/IMPORTDATA/REQUESTDESC/REPORTNAME"), "All Masters")
        self.assertEqual(
            root.findtext("./BODY/IMPORTDATA/REQUESTDESC/STATICVARIABLES/SVCURRENTCOMPANY"),
            "Demo Company",
        )
        ledger = root.find("./BODY/IMPORTDATA/REQUESTDATA/TALLYMESSAGE/LEDGER")
        self.assertIsNotNone(ledger)
        self.assertEqual(ledger.attrib["NAME"], "New Supplier")
        self.assertEqual(ledger.attrib["ACTION"], "Create")
        self.assertEqual(ledger.findtext("PARENT"), "Sundry Creditors")

    def test_create_ledger_tally_error_is_raised(self) -> None:
        client = TallyClient(session=FakeSession([CREATE_LEDGER_ERROR_XML]))
        with self.assertRaises(TallyLedgerCreationError) as raised:
            client.create_ledger("Demo Company", "Duplicate Ledger", "Sundry Creditors")
        self.assertIn("Duplicate ledger name", str(raised.exception))
        self.assertFalse(raised.exception.result.succeeded)  # type: ignore[union-attr]


class LedgerMatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledgers = [
            TallyLedger("Demo Bank A/c", "Bank Accounts"),
            TallyLedger("Demo Traders", "Sundry Creditors"),
            TallyLedger("Cash", "Cash-in-Hand"),
            TallyLedger("Suspense A/c", "Suspense A/c"),
        ]
        self.matcher = LedgerMatcher()

    def test_saved_rule_runs_before_automatic_matching(self) -> None:
        rule = MatchingRule(
            pattern="DEMO", ledger_name="Cash", match_type=RuleMatchType.CONTAINS,
            voucher_type=VoucherType.CONTRA,
        )
        result = self.matcher.match(payment(), self.ledgers, [rule])
        self.assertEqual(result.ledger_name, "Cash")
        self.assertEqual(result.method, "Saved Rule")
        self.assertEqual(result.voucher_type_override, VoucherType.CONTRA)

    def test_matching_sequence_and_suspense_fallback(self) -> None:
        exact = self.matcher.match(payment("Demo Traders"), self.ledgers, [])
        keyword = self.matcher.match(payment("PAY TO DEMO TRADERS VIA UPI"), self.ledgers, [])
        normalized = self.matcher.match(payment("DEMOTRADERS"), self.ledgers, [])
        fuzzy = self.matcher.match(payment("Demmo Tradrs"), self.ledgers, [], 70)
        fallback = self.matcher.match(payment("UNRELATED MERCHANT XYZ"), self.ledgers, [], 99)
        self.assertEqual(exact.method, "Exact ledger name")
        self.assertEqual(keyword.method, "Keyword")
        self.assertEqual(normalized.method, "Normalized text")
        self.assertEqual(fuzzy.method, "Fuzzy")
        self.assertEqual(fallback.ledger_name, "Suspense A/c")
        self.assertEqual(fallback.confidence, Decimal("0"))
        self.assertEqual(
            self.matcher.normalize("UPI/abc@okhdfc/DEMO/123456789012"), "demo"
        )

    def test_apply_sets_confidence_bank_ledger_and_voucher_type(self) -> None:
        item = payment("NEFT DEMO TRADERS")
        counts = self.matcher.apply([item], self.ledgers, [], "Demo Bank A/c")
        self.assertEqual(item.opposite_ledger, "Demo Traders")
        self.assertEqual(item.bank_ledger, "Demo Bank A/c")
        self.assertEqual(item.voucher_type, VoucherType.PAYMENT)
        self.assertEqual(counts["matched"], 1)

    def test_contra_requires_cash_or_bank_opposite_ledger(self) -> None:
        detector = VoucherTypeDetector()
        item = payment("NEFT TRANSFER")
        bank = TallyLedger("Demo Bank A/c", "Bank Accounts")
        vendor = TallyLedger("Vendor", "Sundry Creditors")
        cash = TallyLedger("Cash", "Cash-in-Hand")
        self.assertEqual(detector.detect(item, vendor, bank), VoucherType.PAYMENT)
        self.assertEqual(detector.detect(item, cash, bank), VoucherType.CONTRA)


class MatchingRuleRepositoryTests(unittest.TestCase):
    def test_rule_crud_and_usage_count(self) -> None:
        with TemporaryDirectory() as directory:
            database = DatabaseManager(Path(directory) / "rules.db")
            database.initialize()
            repository = MatchingRuleRepository(database)
            rule = MatchingRule("DEMO TRADERS", "Demo Traders", priority=10)
            repository.save(rule)
            repository.increment_use(rule.id, 3)
            loaded = repository.list_all()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].use_count, 3)
            self.assertEqual(loaded[0].priority, 10)
            repository.delete(rule.id)
            self.assertEqual(repository.list_all(), [])

    def test_numeric_legacy_references_are_preserved_for_manual_reassignment(self) -> None:
        with TemporaryDirectory() as directory:
            database = DatabaseManager(Path(directory) / "legacy.db")
            database.initialize()
            with database.connection() as connection:
                connection.execute(
                    """
                    INSERT INTO matching_rules (
                        id, pattern, ledger_name, created_at, updated_at
                    ) VALUES ('legacy-rule', 'R AINU T O', '169', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                    """
                )
            database.initialize()
            rule = MatchingRuleRepository(database).list_all()[0]
            self.assertEqual(rule.ledger_name, "")
            self.assertEqual(rule.legacy_ledger_reference, "169")


if __name__ == "__main__":
    unittest.main()
