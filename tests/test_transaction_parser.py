import unittest
from datetime import date
from decimal import Decimal

from app.models.enums import VoucherType
from app.models.mapping import ColumnMapping
from app.services.transaction_parser import TransactionParser


def sample_rows() -> list[list[str]]:
    return [
        ["Transaction Date", "Particulars", "Ref No", "Withdrawal", "Deposit", "Balance"],
        ["01/07/2026", "UPI/DEMO/TRADING", "UTR001", "1,250.50", "", "8,749.50"],
        ["02/07/2026", "Interest credit", "", "", "12.75", "8,762.25"],
        ["Transaction Date", "Particulars", "Ref No", "Withdrawal", "Deposit", "Balance"],
        ["", "Closing Balance", "", "", "", "8,762.25"],
        ["not-a-date", "Malformed", "", "10", "", ""],
    ]


class TransactionParserTests(unittest.TestCase):
    def test_suggest_and_parse_split_amount_columns(self) -> None:
        parser = TransactionParser()
        mapping = parser.suggest_mapping(sample_rows())
        self.assertEqual(mapping.transaction_date, 0)
        self.assertEqual(mapping.description, 1)
        self.assertEqual(mapping.debit, 3)
        self.assertEqual(mapping.credit, 4)
        transactions, warnings = parser.parse(sample_rows(), mapping)
        self.assertEqual(len(transactions), 2)
        self.assertEqual(len(warnings), 1)
        self.assertEqual(transactions[0].transaction_date, date(2026, 7, 1))
        self.assertEqual(transactions[0].debit_amount, Decimal("1250.50"))
        self.assertEqual(transactions[0].voucher_type, VoucherType.PAYMENT)
        self.assertEqual(transactions[1].credit_amount, Decimal("12.75"))
        self.assertEqual(transactions[1].voucher_type, VoucherType.RECEIPT)

    def test_single_amount_and_direction_columns(self) -> None:
        rows = [
            ["Date", "Narration", "Amount", "DR/CR"],
            ["03-07-2026", "Cheque payment", "500.00", "DR"],
            ["04-07-2026", "NEFT receipt", "800.00", "CR"],
            ["05-07-2026", "Negative debit", "-15.00", ""],
        ]
        mapping = ColumnMapping(transaction_date=0, description=1, amount=2, dr_cr=3)
        transactions, warnings = TransactionParser().parse(rows, mapping)
        self.assertFalse(warnings)
        self.assertEqual([item.debit_amount for item in transactions], [Decimal("500.00"), Decimal("0.00"), Decimal("15.00")])
        self.assertEqual([item.credit_amount for item in transactions], [Decimal("0.00"), Decimal("800.00"), Decimal("0.00")])

    def test_signed_single_amount_column_needs_no_direction_column(self) -> None:
        rows = [
            ["Date", "Narration", "Amount"],
            ["03-07-2026", "Signed debit", "-500.00"],
            ["04-07-2026", "Signed credit", "+800.00"],
        ]
        mapping = ColumnMapping(transaction_date=0, description=1, amount=2)

        transactions, warnings = TransactionParser().parse(rows, mapping)

        self.assertFalse(mapping.validate())
        self.assertFalse(warnings)
        self.assertEqual(transactions[0].debit_amount, Decimal("500.00"))
        self.assertEqual(transactions[1].credit_amount, Decimal("800.00"))

    def test_mapping_requires_amount_information(self) -> None:
        errors = ColumnMapping(transaction_date=0, description=1).validate()
        self.assertTrue(any("Amount" in error or "Debit" in error for error in errors))

    def test_exact_value_date_alias_does_not_steal_transaction_date(self) -> None:
        mapping = TransactionParser().suggest_mapping([["Value Date", "Transaction Date", "Narration", "Debit"]])
        self.assertEqual(mapping.value_date, 0)
        self.assertEqual(mapping.transaction_date, 1)


if __name__ == "__main__":
    unittest.main()
