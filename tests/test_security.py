import unittest

from app.utils.security import mask_account_numbers, redact_sensitive_data


class SecurityTests(unittest.TestCase):
    def test_masks_account_like_numbers_but_keeps_last_four(self) -> None:
        masked = mask_account_numbers("Account 123456789012 and ref 1234")
        self.assertNotIn("123456789012", masked)
        self.assertTrue(masked.endswith("ref 1234"))
        self.assertEqual(masked.count("9012"), 1)

    def test_redacts_upi_address(self) -> None:
        self.assertEqual(redact_sensitive_data("Pay person.name@bank"), "Pay pe***@bank")


if __name__ == "__main__":
    unittest.main()
