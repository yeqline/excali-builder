import unittest
from unittest.mock import patch

from excali_builder.cli import confirm_full_refresh


class CliTests(unittest.TestCase):
    @patch("builtins.input", return_value="y")
    def test_confirm_full_refresh_accepts_yes(self, _mock_input):
        self.assertTrue(confirm_full_refresh())

    @patch("builtins.input", return_value="No")
    def test_confirm_full_refresh_rejects_non_yes(self, _mock_input):
        self.assertFalse(confirm_full_refresh())

    @patch("builtins.input", side_effect=EOFError)
    def test_confirm_full_refresh_handles_eof_as_cancel(self, _mock_input):
        self.assertFalse(confirm_full_refresh())


if __name__ == "__main__":
    unittest.main()
