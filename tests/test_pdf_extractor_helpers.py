import unittest

from app.services.pdf_extractor import PdfExtractor


class FakeCoordinatePage:
    width = 670
    height = 800

    def __init__(self, words, rects):
        self.words = words
        self.rects = rects

    def extract_words(self, **_kwargs):
        return self.words


class FakeTablePart:
    def __init__(self, bbox):
        self.bbox = bbox


class FakeStackedTable:
    def __init__(self):
        self.columns = [
            FakeTablePart((0, 0, 50, 160)),
            FakeTablePart((50, 0, 220, 160)),
            FakeTablePart((220, 0, 320, 160)),
            FakeTablePart((320, 0, 380, 160)),
            FakeTablePart((380, 0, 460, 160)),
            FakeTablePart((460, 0, 540, 160)),
            FakeTablePart((540, 0, 620, 160)),
        ]
        self.rows = [
            FakeTablePart((0, 0, 620, 20)),
            FakeTablePart((0, 20, 620, 160)),
        ]


class FakeGridlessTable:
    bbox = (0, 0, 620, 20)

    def __init__(self):
        self.columns = [
            FakeTablePart((0, 0, 50, 20)),
            FakeTablePart((50, 0, 150, 20)),
            FakeTablePart((150, 0, 230, 20)),
            FakeTablePart((230, 0, 380, 20)),
            FakeTablePart((380, 0, 470, 20)),
            FakeTablePart((470, 0, 550, 20)),
            FakeTablePart((550, 0, 620, 20)),
        ]

    @staticmethod
    def extract():
        return [[
            "#", "TRANSACTION DATE", "VALUE DATE", "TRANSACTION DETAILS",
            "CHQ / REF NO.", "DEBIT/CREDIT(₹)", "BALANCE(₹)",
        ]]


def word(text: str, x0: float, top: float) -> dict[str, object]:
    return {"text": text, "x0": x0, "top": top}


HEADER_WORDS = [
    word("SlNo", 7, 278),
    word("Transaction", 42, 278),
    word("Date", 86, 278),
    word("Value", 112, 278),
    word("Date", 135, 278),
    word("Particulars", 182, 278),
    word("Cheque", 282, 278),
    word("Number", 312, 278),
    word("Withdrawals", 349, 278),
    word("Deposits", 442, 278),
    word("Balance", 530, 278),
    word("Amount", 561, 278),
]


class PdfHelperTests(unittest.TestCase):
    def test_text_to_rows_splits_columns_and_ignores_blank_lines(self) -> None:
        text = "Date  Description    Debit   Credit\n\n01/01/2026  Sample payment    100.00\n"
        rows = PdfExtractor._text_to_rows(text)
        self.assertEqual(rows[0], ["Date", "Description", "Debit", "Credit"])
        self.assertEqual(rows[1], ["01/01/2026", "Sample payment", "100.00"])

    def test_rectangularize_pads_short_rows(self) -> None:
        self.assertEqual(PdfExtractor._rectangularize([["a", "b"], ["c"]]), [["a", "b"], ["c", ""]])

    def test_coordinate_table_reconstructs_multiline_shaded_rows(self) -> None:
        words = [
            *HEADER_WORDS,
            word("1", 7, 300),
            word("01-Aug-2026", 42, 300),
            word("01-Aug-2026", 112, 300),
            word("Charges", 182, 300),
            word("17.70", 349, 300),
            word("16,238.13", 530, 300),
            word("UPI/TEST/", 182, 326),
            word("2", 7, 350),
            word("03-Aug-2026", 42, 350),
            word("03-Aug-2026", 112, 350),
            word("Payment", 182, 350),
            word("2,000.00", 349, 350),
            word("14,238.13", 530, 350),
            word("reference", 182, 360),
        ]
        rects = [
            {"x0": 7, "x1": 624, "top": 270, "bottom": 292},
            {"x0": 7, "x1": 624, "top": 292, "bottom": 314},
            {"x0": 7, "x1": 624, "top": 319, "bottom": 389},
        ]
        rows, headers, starts = PdfExtractor._extract_coordinate_table(
            FakeCoordinatePage(words, rects), None, None
        )
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0][1:4], ["Transaction Date", "Value Date", "Particulars"])
        self.assertEqual(rows[1][5:], ["17.70", "", "16,238.13"])
        self.assertEqual(rows[2][3], "UPI/TEST/ Payment reference")

        continuation_words = [
            word("UPI/NEXT/", 182, 22),
            word("3", 7, 42),
            word("04-Aug-2026", 42, 42),
            word("04-Aug-2026", 112, 42),
            word("Receipt", 182, 42),
            word("500.00", 442, 42),
            word("14,738.13", 530, 42),
        ]
        continuation_rects = [{"x0": 7, "x1": 624, "top": 15, "bottom": 75}]
        continued, _, _ = PdfExtractor._extract_coordinate_table(
            FakeCoordinatePage(continuation_words, continuation_rects), headers, starts
        )
        self.assertEqual(len(continued), 1)
        self.assertEqual(continued[0][3], "UPI/NEXT/ Receipt")
        self.assertEqual(continued[0][6], "500.00")

    def test_gridless_date_table_handles_repeated_sections_and_multiline_rows(self) -> None:
        words = [
            word("DATE", 10, 100),
            word("PARTICULARS", 80, 100),
            word("CHQ.NO.", 300, 100),
            word("WITHDRAWALS", 380, 100),
            word("DEPOSITS", 470, 100),
            word("BALANCE", 560, 100),
            word("01-07-2026", 10, 120),
            word("NEFT", 80, 120),
            word("receipt", 115, 120),
            word("REF1", 300, 120),
            word("500.00", 470, 120),
            word("1,500.00Cr", 560, 120),
            word("UTR", 80, 132),
            word("ABC", 110, 132),
            word("02-07-2026", 10, 150),
            word("PAYMENT", 80, 150),
            word("REF2", 300, 150),
            word("200.00", 380, 150),
            word("1,300.00Cr", 560, 150),
            word("Cumulative", 80, 180),
            word("Totals:", 145, 180),
            word("DATE", 10, 300),
            word("PARTICULARS", 80, 300),
            word("CHQ.NO.", 300, 300),
            word("WITHDRAWALS", 380, 300),
            word("DEPOSITS", 470, 300),
            word("BALANCE", 560, 300),
            word("03-07-2026", 10, 320),
            word("CASH", 80, 320),
            word("300.00", 470, 320),
            word("1,600.00Cr", 560, 320),
            word("Cumulative", 80, 350),
            word("Totals:", 145, 350),
        ]

        rows = PdfExtractor._extract_gridless_date_table(FakeCoordinatePage(words, []))

        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0], [
            "Date", "Particulars", "Cheque Number", "Withdrawals", "Deposits", "Balance Amount"
        ])
        self.assertEqual(rows[1], [
            "01-07-2026", "NEFT receipt UTR ABC", "REF1", "", "500.00", "1,500.00Cr"
        ])
        self.assertEqual(rows[2][3:], ["200.00", "", "1,300.00Cr"])
        self.assertEqual(rows[4][1], "CASH")

    def test_stacked_table_is_split_using_date_anchors(self) -> None:
        words = [
            word("Date", 5, 5),
            word("Narration", 55, 5),
            word("Chq./Ref.No.", 225, 5),
            word("Value", 325, 5),
            word("Withdrawal", 385, 5),
            word("Deposit", 465, 5),
            word("Balance", 545, 5),
            word("02/04/25", 5, 30),
            word("NEFT", 55, 30),
            word("receipt", 55, 42),
            word("REF1", 225, 30),
            word("02/04/25", 325, 30),
            word("75,000.00", 465, 30),
            word("96,007.14", 545, 30),
            word("04/04/25", 5, 70),
            word("UPI", 55, 70),
            word("payment", 55, 82),
            word("REF2", 225, 70),
            word("04/04/25", 325, 70),
            word("90.00", 385, 70),
            word("95,917.14", 545, 70),
        ]
        page = FakeCoordinatePage(words, [])
        raw = [
            ["Date", "Narration", "Chq./Ref.No.", "Value Dt", "Withdrawal", "Deposit", "Balance"],
            ["02/04/25\n04/04/25", "NEFT receipt\nUPI payment", "REF1\nREF2", "02/04/25\n04/04/25", "90.00", "75,000.00", "96,007.14\n95,917.14"],
        ]
        cleaned = PdfExtractor._clean_table(raw)

        rows = PdfExtractor._expand_stacked_table(page, FakeStackedTable(), raw, cleaned)

        self.assertEqual(rows[0][0], "Date")
        self.assertEqual(rows[1], ["02/04/25", "NEFT receipt", "REF1", "02/04/25", "", "75,000.00", "96,007.14"])
        self.assertEqual(rows[2], ["04/04/25", "UPI payment", "REF2", "04/04/25", "90.00", "", "95,917.14"])

    def test_stacked_table_preserves_leading_page_continuation(self) -> None:
        table = FakeStackedTable()
        table.rows = [FakeTablePart((0, 20, 620, 160))]
        words = [
            word("continued", 55, 22),
            word("narration", 55, 32),
            word("05/04/25", 5, 50),
            word("Payment", 55, 50),
            word("REF3", 225, 50),
            word("05/04/25", 325, 50),
            word("100.00", 385, 50),
            word("95,817.14", 545, 50),
            word("06/04/25", 5, 90),
            word("Receipt", 55, 90),
            word("REF4", 225, 90),
            word("06/04/25", 325, 90),
            word("50.00", 465, 90),
            word("95,867.14", 545, 90),
        ]
        page = FakeCoordinatePage(words, [])
        raw = [["05/04/25\n06/04/25", "continued narration\nPayment\nReceipt", "REF3\nREF4", "05/04/25\n06/04/25", "100.00", "50.00", "95,817.14\n95,867.14"]]

        rows = PdfExtractor._expand_stacked_table(page, table, raw, PdfExtractor._clean_table(raw))

        self.assertEqual(rows[0], ["", "continued narration", "", "", "", "", ""])
        self.assertEqual(rows[1][0:2], ["05/04/25", "Payment"])
        self.assertEqual(rows[2][0:2], ["06/04/25", "Receipt"])

    def test_gridless_serial_table_reconstructs_signed_amount_rows(self) -> None:
        words = [
            word("1", 5, 30),
            word("23", 55, 30),
            word("Apr", 70, 30),
            word("2025", 90, 30),
            word("23", 155, 30),
            word("Apr", 170, 30),
            word("2025", 190, 30),
            word("Card", 235, 30),
            word("dues", 260, 30),
            word("debited", 285, 30),
            word("VP-1", 385, 30),
            word("-10,772.45", 475, 30),
            word("14,090.30", 555, 30),
            word("11:14", 55, 42),
            word("AM", 85, 42),
            word("2", 5, 70),
            word("28", 55, 70),
            word("Apr", 70, 70),
            word("2025", 90, 70),
            word("28", 155, 70),
            word("Apr", 170, 70),
            word("2025", 190, 70),
            word("NEFT", 235, 70),
            word("DEMO", 265, 70),
            word("REF-2", 385, 70),
            word("+12,500.00", 475, 70),
            word("26,590.30", 555, 70),
            word("Statement", 0, 150),
            word("generated", 50, 150),
            word("on", 100, 150),
        ]
        page = FakeCoordinatePage(words, [])
        page.height = 200

        rows = PdfExtractor._extract_gridless_serial_table(page, [FakeGridlessTable()])

        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][1], "23 Apr 2025 11:14 AM")
        self.assertEqual(rows[1][3:7], ["Card dues debited", "VP-1", "-10,772.45", "14,090.30"])
        self.assertEqual(rows[2][1:7], ["28 Apr 2025", "28 Apr 2025", "NEFT DEMO", "REF-2", "+12,500.00", "26,590.30"])

    def test_projection_aligns_coordinate_continuation_columns(self) -> None:
        source_headers = [
            "SlNo",
            "Transaction Date",
            "Value Date",
            "Particulars",
            "Cheque Number",
            "Withdrawals",
            "Deposits",
            "Balance Amount",
        ]
        target_headers = ["Date", "Particulars", "Withdrawals", "Deposits", "Balance Amount"]
        rows = [[
            "9",
            "11-Aug-2026",
            "11-Aug-2026",
            "UPI/SBIN/217939693028",
            "",
            "500.00",
            "",
            "653.53",
        ]]

        projected = PdfExtractor._project_rows_to_headers(rows, source_headers, target_headers)

        self.assertEqual(
            projected[0],
            ["11-Aug-2026", "UPI/SBIN/217939693028", "500.00", "", "653.53"],
        )

    def test_statement_header_row_recognises_common_columns(self) -> None:
        self.assertTrue(
            PdfExtractor._is_statement_header_row(
                ["Date", "Particulars", "Withdrawals", "Deposits", "Balance Amount"]
            )
        )
        self.assertFalse(
            PdfExtractor._is_statement_header_row(
                ["08-Aug-2026", "UPI payment", "500.00", "", "653.53"]
            )
        )

if __name__ == "__main__":
    unittest.main()
