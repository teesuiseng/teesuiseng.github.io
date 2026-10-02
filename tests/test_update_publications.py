import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from scripts import update_publications


def work(*, title="A study", year="2026", doi="10.1000/example"):
    return {
        "title": {"title": {"value": title}},
        "publication-date": {"year": {"value": year}},
        "journal-title": {"value": "Example Journal"},
        "external-ids": {
            "external-id": [
                {"external-id-type": "doi", "external-id-value": doi}
            ]
        },
        "contributors": {
            "contributor": [
                {"credit-name": {"value": "Alex Researcher"}},
                {"credit-name": {"value": "Sui-Seng Tee"}},
            ]
        },
    }


class FetchTests(unittest.TestCase):
    @patch("scripts.update_publications.time.sleep")
    @patch("scripts.update_publications.urlopen")
    def test_retries_a_temporary_http_error(self, urlopen, sleep):
        response = MagicMock()
        response.__enter__.return_value = io.StringIO('{"group": []}')
        urlopen.side_effect = [
            HTTPError("https://example.test", 503, "Unavailable", {}, None),
            response,
        ]

        self.assertEqual(update_publications.fetch_json("https://example.test"), {"group": []})
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1)

    @patch("scripts.update_publications.time.sleep")
    @patch("scripts.update_publications.urlopen")
    def test_raises_clear_error_after_retries(self, urlopen, sleep):
        urlopen.side_effect = HTTPError(
            "https://example.test", 503, "Unavailable", {}, None
        )
        with self.assertRaises(update_publications.SourceUnavailableError):
            update_publications.fetch_json("https://example.test")
        self.assertEqual(urlopen.call_count, update_publications.FETCH_ATTEMPTS)


class OrcidTests(unittest.TestCase):
    def test_parses_structured_work(self):
        publication = update_publications.parse_work(work())

        self.assertEqual(publication.title, "A study")
        self.assertEqual(publication.authors, ("Alex Researcher", "Sui-Seng Tee"))
        self.assertEqual(publication.venue, "Example Journal")
        self.assertEqual(publication.doi, "10.1000/example")

    @patch("scripts.update_publications.fetch_json")
    def test_fetches_details_and_deduplicates_grouped_works(self, fetch_json):
        fetch_json.side_effect = [
            {
                "group": [
                    {
                        "work-summary": [
                            {
                                "put-code": 42,
                                "publication-date": {"year": {"value": "2026"}},
                            }
                        ]
                    }
                ]
            },
            work(),
        ]

        publications = update_publications.orcid_publications()

        self.assertEqual(len(publications), 1)
        self.assertEqual(fetch_json.call_args_list[-1].args[0], f"{update_publications.ORCID_API}/work/42")

    def test_renders_semantic_year_groups_and_doi_links(self):
        rendered = update_publications.render_publications(
            [update_publications.parse_work(work())]
        )

        self.assertIn('aria-labelledby="year-2026"', rendered)
        self.assertIn('href="https://doi.org/10.1000/example"', rendered)
        self.assertIn("<strong>Sui-Seng Tee</strong>", rendered)


class MainTests(unittest.TestCase):
    @patch("scripts.update_publications.orcid_publications")
    def test_unavailable_orcid_preserves_existing_page(self, publications):
        publications.side_effect = update_publications.SourceUnavailableError("offline")
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
            self.assertIn("::warning title=ORCID unavailable::", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
