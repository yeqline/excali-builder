import unittest
from unittest.mock import patch

from excali_builder.cli import confirm_full_refresh, parse_args


class CliTests(unittest.TestCase):
    def test_parse_build_command_keeps_original_positional_form(self):
        args = parse_args(["--full-refresh", "diagram-folder"])

        self.assertEqual(args.command, "build")
        self.assertEqual(args.folder, "diagram-folder")
        self.assertTrue(args.full_refresh)

    def test_parse_serve_command(self):
        args = parse_args(
            [
                "serve",
                "diagram-folder",
                "--host",
                "0.0.0.0",
                "--port",
                "0",
                "--poll-interval",
                "0.25",
                "--no-open",
            ]
        )

        self.assertEqual(args.command, "serve")
        self.assertEqual(args.folder, "diagram-folder")
        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 0)
        self.assertEqual(args.poll_interval, 0.25)
        self.assertTrue(args.no_open)

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
