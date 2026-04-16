"""
The Wire scraper — parses the RSS feed for reviewed items.
Review titles follow the pattern: "Tagline": Artist reviewed
or: "Tagline": Artist Album reviewed

For items matching the pattern, fetches the article page to extract
the album title from the body text.
"""
import re
import requests
from bs4 import BeautifulSoup

RSS_URL = "https://www.thewire.co.uk/rss"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-GB,en;q=0.9",
}


def scrape(limit: int = 15) -> list[dict]:
    candidates: list[dict] = []
    try:
        r = requests.get(RSS_URL, headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")

        for item in items:
            title_el = item.find("title")
            link_el = item.find("link")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            link = link_el.get_text(strip=True) if link_el else ""

            if "reviewed" not in title.lower():
                continue

            candidate = _parse_review_title(title, link)
            if candidate:
                candidates.append(candidate)
            if len(candidates) >= limit:
                break
    except Exception as e:
        print(f"[the_wire] error: {e}")

    print(f"[the_wire] {len(candidates)} candidates")
    return candidates


def _parse_review_title(title: str, link: str) -> dict | None:
    """
    Title format: '"Tagline": Artist [Album] reviewed'
    Extract artist (and optionally album) from the title, then fetch
    the article page to get the album title.
    """
    try:
        # Strip the leading "Tagline": prefix
        # Match: anything after the first colon+space (or just the whole title if no quote pattern)
        m = re.match(r'^["\u201c].+?["\u201d]:\s*(.+?)\s+reviewed\s*$', title, re.IGNORECASE)
        if not m:
            m = re.match(r'^(.+?)\s+reviewed\s*$', title, re.IGNORECASE)
        if not m:
            return None

        subject = m.group(1).strip()

        # Fetch the article page to get artist + album from body
        artist, album, excerpt = _fetch_article_details(link, subject)

        return {
            "artist": artist,
            "album": album,
            "source": "The Wire",
            "excerpt": excerpt,
            "score": None,
        }
    except Exception:
        return None


def _fetch_article_details(url: str, fallback_artist: str) -> tuple[str, str, str]:
    """
    Fetch a Wire review page and extract artist, album, and excerpt.
    The article body contains a "discography card" block:
        <artist line>
        <album line>
        <label + format line>  ← contains CD/LP/DL/Vinyl
    """
    if not url:
        return fallback_artist, "", ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=12)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        og_desc = ""
        og_el = soup.find("meta", property="og:description")
        if og_el:
            og_desc = og_el.get("content", "").strip()

        main = soup.find("main") or soup.find("article")
        if not main:
            return fallback_artist, "", og_desc[:250]

        lines = [l.strip() for l in main.get_text(separator="\n", strip=True).split("\n") if l.strip()]

        artist = fallback_artist
        album = ""

        # The discography card pattern:
        # Line N:   artist name (exact or close match to fallback_artist)
        # Line N+1: album title
        # Line N+2: label + format (contains CD/LP/DL/Vinyl/digital)
        format_keywords = {"cd", "lp", "dl", "vinyl", "digital", "cassette", "tape"}
        for i, line in enumerate(lines[:30]):
            if fallback_artist.lower() in line.lower() and len(line) < 80:
                # Check if the line after next is a format line
                if i + 2 < len(lines):
                    candidate_album = lines[i + 1]
                    format_line = lines[i + 2].lower()
                    if any(k in format_line for k in format_keywords):
                        album = candidate_album
                        artist = line  # use exact name from article
                        break
                # Fallback: next non-empty line under 80 chars that isn't a date/format
                if not album and i + 1 < len(lines):
                    candidate_album = lines[i + 1]
                    if (
                        len(candidate_album) < 80
                        and not any(k in candidate_album.lower() for k in format_keywords)
                        and not re.match(r"^\d{4}$", candidate_album)
                    ):
                        album = candidate_album

        excerpt = og_desc[:250] if og_desc else ""
        return artist, album, excerpt
    except Exception:
        return fallback_artist, "", ""
