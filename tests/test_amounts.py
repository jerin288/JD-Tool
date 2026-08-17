import unittest
from decimal import Decimal

from app.utils.amounts import parse_decimal


class AmountTests(unittest.TestCase):
    def test_parse_decimal(self) -> None:
        cases = [
            ("1,23,456.78", Decimal("123456.78")),
            ("₹ 250.5", Decimal("250.50")),
            ("(1,000.00)", Decimal("-1000.00")),
            ("-42", Decimal("-42.00")),
            ("-", Decimal("0.00")),
            (None, Decimal("0.00")),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(parse_decimal(raw), expected)

    def test_rejects_non_finite_amount(self) -> None:
        with self.assertRaises(ValueError):
            parse_decimal("Infinity")


if __name__ == "__main__":
    unittest.main()
