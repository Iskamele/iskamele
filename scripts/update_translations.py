"""Keep the Ukrainify cards in README.md in sync with the translation repos.

Every repository of the owner that carries the `ukrainify` topic and a
`ukrainify.json` manifest becomes one card: cover, link, progress and size.
The cards replace whatever sits between the two markers below; the rest of
the README is never touched. Any failure leaves README.md as it was.

Usage:
    python3 scripts/update_translations.py     (GITHUB_TOKEN is used if set)
"""
from __future__ import annotations

import html
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Sequence

START, END = "<!-- ukrainify:start -->", "<!-- ukrainify:end -->"
OWNER = "Iskamele"
GITHUB_API = "https://api.github.com/"
COVERS = "assets/covers"  # where the README finds a cover kept in this repo

Fetch = Callable[[str], Optional[object]]


@dataclass(frozen=True)
class Translation:
    repo: str
    url: str
    game: str
    lines_done: int
    lines_total: int
    edited: int | None
    images_total: int
    version: str | None
    cover: str


def pct(n: int, total: int) -> str:
    """Like tools/status.py in the Dune repo: rounded down, never a false 100%."""
    p = 100.0 * n / max(1, total)
    return "0%" if n == 0 else "<1%" if p < 1 else "%d%%" % p


def fmt_int(n: int) -> str:
    return "{:,}".format(n).replace(",", " ")


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def render_card(t: Translation) -> str:
    status = "Переклад " + pct(min(t.lines_done, t.lines_total), t.lines_total)
    if t.edited is not None:
        status += " · редактура " + pct(min(t.edited, t.lines_total), t.lines_total)
    status += " · версія " + t.version if t.version else " · у роботі"

    if t.lines_done >= t.lines_total:
        size = "%s %s" % (fmt_int(t.lines_total), plural(t.lines_total, "репліка", "репліки", "реплік"))
        if t.images_total > 0:
            size += " · %s %s" % (fmt_int(t.images_total),
                                  plural(t.images_total, "зображення", "зображення", "зображень"))
    else:
        rows = "рядка" if t.lines_total % 10 == 1 and t.lines_total % 100 != 11 else "рядків"
        size = "%s із %s %s" % (fmt_int(t.lines_done), fmt_int(t.lines_total), rows)

    return (
        '<td width="50%" valign="top">\n'
        '<a href="{url}"><img src="{cover}" alt="{alt}"></a>\n'
        "\n"
        "**[{game}]({url})**<br>\n"
        "{status}<br>\n"
        "{size}\n"
        "</td>"
    ).format(url=t.url, cover=html.escape(t.cover), alt=html.escape(t.game),
             game=html.escape(t.game, quote=False), status=status, size=size)


def render_block(ts: Sequence[Translation]) -> str:
    ordered = sorted(ts, key=lambda t: (-t.lines_done / max(1, t.lines_total), t.game))
    rows = []
    for i in range(0, len(ordered), 2):
        cells = [render_card(t) for t in ordered[i:i + 2]]
        if len(cells) == 1:
            cells.append('<td width="50%"></td>')
        rows.append("<tr>\n" + "\n".join(cells) + "\n</tr>")
    return "<table>\n" + "\n".join(rows) + "\n</table>"


def replace_block(readme: str, block: str) -> str:
    start, end = readme.find(START), readme.find(END)
    if start < 0 or end < start:
        raise ValueError("README.md has no %s ... %s block" % (START, END))
    return readme[:start + len(START)] + "\n" + block + "\n" + readme[end:]


def parse_manifest(data: object) -> dict:
    """Check a ukrainify.json: game, steam_appid and lines are required."""
    def need(ok: bool, field: str) -> None:
        if not ok:
            raise ValueError("ukrainify.json: bad or missing %r" % field)

    is_int = lambda v: isinstance(v, int) and not isinstance(v, bool)
    need(isinstance(data, dict), "manifest")
    need(isinstance(data.get("game"), str), "game")
    need(is_int(data.get("steam_appid")), "steam_appid")
    lines = data.get("lines")
    need(isinstance(lines, dict) and is_int(lines.get("done")) and is_int(lines.get("total")), "lines")
    need("edited" not in data or is_int(data["edited"]), "edited")
    images = data.get("images", {})
    need(isinstance(images, dict) and is_int(images.get("total", 0)), "images")
    return data


def fetch_json(url: str, token: str | None = None) -> object | None:
    """GET a JSON document; None on 404. The token only ever goes to the GitHub API."""
    request = urllib.request.Request(url, headers={"User-Agent": "iskamele-profile",
                                                   "Accept": "application/json"})
    if token and url.startswith(GITHUB_API):
        # unredirected: urllib copies ordinary headers to wherever a redirect points
        request.add_unredirected_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def cover(fetch: Fetch, name: str, appid: int, covers_dir: Path) -> str:
    if (covers_dir / (name + ".jpg")).is_file():
        return "%s/%s.jpg" % (COVERS, name)
    details = fetch("https://store.steampowered.com/api/appdetails?appids=%d" % appid) or {}
    image = ((details.get(str(appid)) or {}).get("data") or {}).get("header_image")
    if not image:
        raise ValueError("%s: no cover in %s and none on Steam for app %d" % (name, covers_dir, appid))
    return image


def collect(fetch: Fetch, covers_dir: Path, owner: str = OWNER) -> list[Translation]:
    found = fetch(GITHUB_API + "search/repositories?q=user:%s+topic:ukrainify&per_page=100" % owner)
    translations = []
    for repo in (found or {}).get("items", []):
        name, full = repo["name"], repo["full_name"]
        data = fetch("https://raw.githubusercontent.com/%s/%s/ukrainify.json" % (full, repo["default_branch"]))
        if data is None:
            print("%s: no ukrainify.json, skipped" % full, file=sys.stderr)
            continue
        m = parse_manifest(data)
        release = fetch(GITHUB_API + "repos/%s/releases/latest" % full)
        translations.append(Translation(
            repo=name, url=repo["html_url"], game=m["game"],
            lines_done=m["lines"]["done"], lines_total=m["lines"]["total"],
            edited=m.get("edited"), images_total=m.get("images", {}).get("total", 0),
            version=release["tag_name"] if release else None,
            cover=cover(fetch, name, m["steam_appid"], covers_dir),
        ))
    return translations


def main(fetch: Fetch | None = None, readme_path: Path = Path("README.md"),
         covers_dir: Path = Path(COVERS)) -> int:
    if fetch is None:
        token = os.environ.get("GITHUB_TOKEN")
        fetch = lambda url: fetch_json(url, token)
    try:
        translations = collect(fetch, covers_dir)
        if not translations:
            raise ValueError("no repository has the ukrainify topic and a manifest")
        old = readme_path.read_text(encoding="utf-8")
        new = replace_block(old, render_block(translations))
    except Exception as e:  # any failure: say why and leave the README as it was
        print("update_translations: %s" % e, file=sys.stderr)
        return 1
    if new == old:
        print("no changes")
    else:
        readme_path.write_text(new, encoding="utf-8")
        print("updated README.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
