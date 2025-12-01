import unittest
from unittest.mock import MagicMock, patch

from backend.base.helpers import CommaList
from backend.features.search import _matches_allowed_formats
from backend.internals import settings as settings_module


class SettingsAllowedFormatsTest(unittest.TestCase):
    def setUp(self):
        # Patch DB interactions in settings so we can safely construct Settings
        self.get_db_patcher = patch.object(settings_module, "get_db")
        self.commit_patcher = patch.object(settings_module, "commit")

        self.mock_get_db = self.get_db_patcher.start()
        self.mock_commit = self.commit_patcher.start()

        # Simple stub cursor with executemany
        self.mock_cursor = MagicMock()
        self.mock_get_db.return_value = self.mock_cursor

    def tearDown(self):
        self.get_db_patcher.stop()
        self.commit_patcher.stop()

    def test_format_value_converts_list_to_commalist(self):
        """__format_value should turn a list into CommaList for allowed_formats."""
        s = settings_module.Settings()

        value = s._Settings__format_value(  # type: ignore[attr-defined]
            "allowed_formats", ["cbr", "cbz"], True
        )

        self.assertIsInstance(value, CommaList)
        self.assertEqual(list(value), ["cbr", "cbz"])

    def test_update_persists_commalist_as_string(self):
        """update() should persist allowed_formats to DB as a comma string."""
        s = settings_module.Settings()

        # Ensure our stub cursor is used
        self.mock_cursor.executemany.reset_mock()

        s.update({"allowed_formats": ["cbr", "cbz"]}, from_public=True)

        # executemany is called with an iterator of (value, key) tuples
        args, _ = self.mock_cursor.executemany.call_args
        self.assertEqual(args[0], "UPDATE config SET value = ? WHERE key = ?;")
        rows = list(args[1])

        # There should be an entry for allowed_formats stored as "cbr,cbz"
        self.assertIn(("cbr,cbz", "allowed_formats"), rows)


class SearchAllowedFormatsTest(unittest.TestCase):
    def test_no_allowed_formats_accepts_all(self):
        """When allowed_formats is empty, all results should be accepted."""
        with patch("backend.features.search.Settings") as MockSettings:
            MockSettings.return_value.sv.allowed_formats = CommaList("")

            result = {"display_title": "Series 001.pdf"}
            self.assertTrue(_matches_allowed_formats(result))

    def test_filters_by_extension(self):
        """Only results whose title matches one of the allowed extensions pass."""
        with patch("backend.features.search.Settings") as MockSettings:
            MockSettings.return_value.sv.allowed_formats = CommaList("cbr,cbz")

            cbr_result = {"display_title": "Series 001.cbr"}
            cbz_result = {"display_title": "Series 001.cbz"}
            pdf_result = {"display_title": "Series 001.pdf"}

            self.assertTrue(_matches_allowed_formats(cbr_result))
            self.assertTrue(_matches_allowed_formats(cbz_result))
            self.assertFalse(_matches_allowed_formats(pdf_result))
