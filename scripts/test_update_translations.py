import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

from unittest import mock

import update_translations
from update_translations import (
    Translation, fetch_json, fmt_int, main, parse_manifest, pct, plural,
    render_block, render_card, replace_block,
)

DUNE = Translation(
    "Ukrainify-Dune-Spice-Wars", "https://github.com/Iskamele/Ukrainify-Dune-Spice-Wars",
    "Dune: Spice Wars", 9714, 18972, 1800, 0, None,
    "assets/covers/Ukrainify-Dune-Spice-Wars.jpg",
)
BTF = Translation(
    "Ukrainify-Behind-the-Frame-The-Finest-Scenery",
    "https://github.com/Iskamele/Ukrainify-Behind-the-Frame-The-Finest-Scenery",
    "Behind the Frame: The Finest Scenery", 703, 703, None, 85, "1.1",
    "assets/covers/Ukrainify-Behind-the-Frame-The-Finest-Scenery.jpg",
)


def card(**changes):
    fields = dict(DUNE.__dict__)
    fields.update(changes)
    return Translation(**fields)


class PctTest(unittest.TestCase):
    def test_zero_is_plain_zero(self):
        self.assertEqual(pct(0, 10), "0%")

    def test_under_one_percent(self):
        self.assertEqual(pct(1, 1000), "<1%")

    def test_rounds_down(self):
        self.assertEqual(pct(9714, 18972), "51%")
        self.assertEqual(pct(996, 1000), "99%")

    def test_zero_total_does_not_crash(self):
        pct(5, 0)


class NumbersTest(unittest.TestCase):
    def test_thousands_use_no_break_space(self):
        self.assertEqual(fmt_int(9714), "9 714")
        self.assertEqual(fmt_int(703), "703")

    def test_ukrainian_plural(self):
        forms = ("репліка", "репліки", "реплік")
        cases = {1: "репліка", 2: "репліки", 5: "реплік", 11: "реплік",
                 21: "репліка", 22: "репліки", 112: "реплік"}
        for n, expected in cases.items():
            self.assertEqual(plural(n, *forms), expected, n)


class CardTest(unittest.TestCase):
    def test_unfinished_card(self):
        text = render_card(DUNE)
        self.assertIn("Переклад 51% · редактура 9% · у роботі", text)
        self.assertIn("9 714 із 18 972 рядків", text)
        self.assertIn('alt="Dune: Spice Wars"', text)
        self.assertIn("**[Dune: Spice Wars](https://github.com/Iskamele/Ukrainify-Dune-Spice-Wars)**", text)

    def test_finished_card(self):
        text = render_card(BTF)
        self.assertIn("Переклад 100% · версія 1.1", text)
        self.assertIn("703 репліки · 85 зображень", text)
        self.assertNotIn("редактура", text)

    def test_finished_card_without_images(self):
        text = render_card(card(lines_done=703, lines_total=703, images_total=0))
        self.assertIn("703 репліки", text)
        self.assertNotIn("703 репліки ·", text)

    def test_genitive_after_iz(self):
        self.assertIn("21 із 30 рядків", render_card(card(lines_done=21, lines_total=30)))
        self.assertIn("5 із 21 рядка", render_card(card(lines_done=5, lines_total=21)))

    def test_done_over_total_counts_as_finished(self):
        self.assertNotIn(" із ", render_card(card(lines_done=710, lines_total=703)))

    def test_percentages_stop_at_100(self):
        text = render_card(card(lines_done=800, lines_total=703, edited=900))
        self.assertIn("Переклад 100% · редактура 100%", text)

    def test_markup_in_names_is_escaped(self):
        text = render_card(card(game='Tom & "Jerry"'))
        self.assertIn('alt="Tom &amp; &quot;Jerry&quot;"', text)


class BlockTest(unittest.TestCase):
    def test_most_complete_first_in_one_row(self):
        text = render_block([DUNE, BTF])
        self.assertLess(text.index("Behind the Frame"), text.index("Dune: Spice Wars"))
        self.assertEqual(text.count("<tr>"), 1)
        self.assertEqual(text.count('<td width="50%" valign="top">'), 2)

    def test_odd_count_pads_the_row(self):
        self.assertIn('<td width="50%"></td>', render_block([DUNE]))


class ReplaceBlockTest(unittest.TestCase):
    README = "a\n<!-- ukrainify:start -->\nold\n<!-- ukrainify:end -->\nb"
    EXPECTED = "a\n<!-- ukrainify:start -->\nX\n<!-- ukrainify:end -->\nb"

    def test_replaces_between_markers(self):
        self.assertEqual(replace_block(self.README, "X"), self.EXPECTED)

    def test_is_idempotent(self):
        self.assertEqual(replace_block(self.EXPECTED, "X"), self.EXPECTED)

    def test_missing_markers_raise(self):
        with self.assertRaises(ValueError):
            replace_block("no markers here", "X")


DUNE_MANIFEST = {"game": "Dune: Spice Wars", "steam_appid": 1605220,
                 "lines": {"done": 9714, "total": 18972}, "edited": 1800}
BTF_MANIFEST = {"game": "Behind the Frame: The Finest Scenery", "steam_appid": 1634150,
                "lines": {"done": 703, "total": 703}, "images": {"done": 85, "total": 85}}

SEARCH = "https://api.github.com/search/repositories?q=user:Iskamele+topic:ukrainify&per_page=100"
STEAM_HEADER = "https://shared.steamstatic.com/store_item_assets/steam/apps/1605220/header.jpg"


def repo(name):
    return {"name": name, "full_name": "Iskamele/" + name,
            "html_url": "https://github.com/Iskamele/" + name, "default_branch": "main"}


def raw(name):
    return "https://raw.githubusercontent.com/Iskamele/%s/main/ukrainify.json" % name


def release(name):
    return "https://api.github.com/repos/Iskamele/%s/releases/latest" % name


DUNE_REPO, BTF_REPO = "Ukrainify-Dune-Spice-Wars", "Ukrainify-Behind-the-Frame-The-Finest-Scenery"

RESPONSES = {
    SEARCH: {"items": [repo(DUNE_REPO), repo(BTF_REPO)]},
    raw(DUNE_REPO): DUNE_MANIFEST,
    raw(BTF_REPO): BTF_MANIFEST,
    release(DUNE_REPO): None,
    release(BTF_REPO): {"tag_name": "1.1"},
    "https://store.steampowered.com/api/appdetails?appids=1605220":
        {"1605220": {"success": True, "data": {"header_image": STEAM_HEADER}}},
}

README = "# Me\n\n<!-- ukrainify:start -->\n<!-- ukrainify:end -->\n\nBye\n"


class ManifestTest(unittest.TestCase):
    def test_lines_are_required(self):
        with self.assertRaisesRegex(ValueError, "lines"):
            parse_manifest({"game": "X", "steam_appid": 1})

    def test_edited_and_images_are_optional(self):
        self.assertEqual(parse_manifest(DUNE_MANIFEST)["lines"]["done"], 9714)


class FetchTest(unittest.TestCase):
    def headers_sent(self, url):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with mock.patch.object(update_translations.urllib.request, "urlopen", return_value=response) as urlopen:
            fetch_json(url, token="secret")
        return {k.lower(): v for k, v in urlopen.call_args[0][0].header_items()}

    def test_token_goes_to_the_github_api(self):
        self.assertEqual(self.headers_sent(SEARCH)["authorization"], "Bearer secret")

    def test_token_is_not_carried_over_a_redirect(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b"{}"
        with mock.patch.object(update_translations.urllib.request, "urlopen", return_value=response) as urlopen:
            fetch_json(SEARCH, token="secret")
        request = urlopen.call_args[0][0]
        self.assertNotIn("Authorization", request.headers)  # redirects copy only these
        self.assertEqual(request.unredirected_hdrs["Authorization"], "Bearer secret")

    def test_token_never_leaves_the_github_api(self):
        self.assertNotIn("authorization", self.headers_sent(STEAM_HEADER))
        self.assertNotIn("authorization", self.headers_sent(raw(DUNE_REPO)))


class MainTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.readme = self.dir / "README.md"
        self.readme.write_text(README, encoding="utf-8")
        self.covers = self.dir / "assets" / "covers"
        self.covers.mkdir(parents=True)
        (self.covers / (BTF_REPO + ".jpg")).write_bytes(b"jpg")

    def run_main(self, responses):
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            return main(fetch=responses.get, readme_path=self.readme, covers_dir=self.covers)

    def test_renders_every_repo(self):
        self.assertEqual(self.run_main(RESPONSES), 0)
        text = self.readme.read_text(encoding="utf-8")
        self.assertIn("Dune: Spice Wars", text)
        self.assertIn("Behind the Frame: The Finest Scenery", text)
        self.assertIn('src="%s"' % STEAM_HEADER, text)
        self.assertIn('src="assets/covers/%s.jpg"' % BTF_REPO, text)
        self.assertIn("версія 1.1", text)

    def test_no_repos_leaves_readme_alone(self):
        self.assertEqual(self.run_main(dict(RESPONSES, **{SEARCH: {"items": []}})), 1)
        self.assertEqual(self.readme.read_text(encoding="utf-8"), README)

    def test_repo_without_manifest_is_skipped(self):
        self.assertEqual(self.run_main(dict(RESPONSES, **{raw(DUNE_REPO): None})), 0)
        text = self.readme.read_text(encoding="utf-8")
        self.assertNotIn("Dune: Spice Wars", text)
        self.assertIn("Behind the Frame", text)

    def test_unresolvable_cover_leaves_readme_alone(self):
        steam = "https://store.steampowered.com/api/appdetails?appids=1605220"
        self.assertEqual(self.run_main(dict(RESPONSES, **{steam: None})), 1)
        self.assertEqual(self.readme.read_text(encoding="utf-8"), README)

    def test_second_run_changes_nothing(self):
        self.run_main(RESPONSES)
        first = self.readme.read_bytes()
        self.run_main(RESPONSES)
        self.assertEqual(self.readme.read_bytes(), first)


if __name__ == "__main__":
    unittest.main()
