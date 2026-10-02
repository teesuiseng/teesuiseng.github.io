import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scripts import update_publications


class FetchTests(unittest.TestCase):
    @patch("scripts.update_publications.time.sleep")
    @patch("scripts.update_publications.urlopen")
    def test_retries_a_temporary_http_error(self, urlopen, sleep):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"publications"
        urlopen.side_effect = [
            HTTPError("https://example.test", 403, "Forbidden", {}, None),
            response,
        ]

        self.assertEqual(
            update_publications.fetch("https://example.test"), "publications"
        )
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch("scripts.update_publications.time.sleep")
    @patch("scripts.update_publications.urlopen")
    def test_raises_clear_error_after_retries(self, urlopen, sleep):
        urlopen.side_effect = HTTPError(
            "https://example.test", 403, "Forbidden", {}, None
        )

        with self.assertRaises(update_publications.ScholarUnavailableError):
            update_publications.fetch("https://example.test")

        self.assertEqual(urlopen.call_count, update_publications.FETCH_ATTEMPTS)


class MainTests(unittest.TestCase):
    @patch("scripts.update_publications.scholar_pages")
    def test_unavailable_scholar_preserves_existing_page(self, scholar_pages):
        scholar_pages.side_effect = update_publications.ScholarUnavailableError(
            "HTTP Error 403: Forbidden"
        )
        with tempfile.TemporaryDirectory() as directory:
            page = Path(directory, "index.html")
            page.write_text("existing publications")
            stderr = io.StringIO()
            with (
                patch.object(update_publications, "PUBLICATIONS_PAGE", page),
                patch("sys.stderr", stderr),
            ):
                result = update_publications.main()

            self.assertEqual(result, 0)
            self.assertEqual(page.read_text(), "existing publications")
            self.assertIn(
                "::warning title=Google Scholar unavailable::", stderr.getvalue()
            )


if __name__ == "__main__":
    unittest.main()
