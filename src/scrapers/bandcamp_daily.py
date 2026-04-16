"""
Bandcamp Daily scraper — fetches album-of-the-day entries.
Links on the page follow the format: /album-of-the-day/artist-album-review
Link text is: "Artist, "Album Title""
"""
import re
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "Chrome/120.0.0.0 Safari/537.36",
}


def scrape(limit: int = 20) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    try:
        r = requests.get("https://daily.bandcamp.com/album-of-the-day", headers=HEADERS, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")

        # Links with non-empty text to album-of-the-day pages
        links = soup.find_all(
            "a",
            href=lambda h: h and "/album-of-the-day/" in h,
        )
        for link in links:
            text = link.get_text(strip=True)
            if not text:
                continue
            candidate = _parse_link_text(text)
            if candidate:
                key = candidate["album"] + candidate["artist"]
                if key not in seen:
                    candidates.append(candidate)
                    seen.add(key)
            if len(candidates) >= limit:
                break
    except Exception as e:
        print(f"[bandcamp_daily] error: {e}")

    print(f"[bandcamp_daily] {len(candidates)} candidates")
    return candidates


def _parse_link_text(text: str) -> dict | None:
    """
    Parse text in the format: 'Artist, "Album Title"'
    or 'Artist, Album Title'
    """
    try:
        # Format: Artist, "Album"  or  Artist, Album
        m = re.match(r'^(.+?),\s*["\u201c\u201d]?(.+?)["\u201c\u201d]?$', text)
        if m:
            artist = m.group(1).strip().strip('"').strip('\u201c').strip('\u201d')
            album = m.group(2).strip().strip('"').strip('\u201c').strip('\u201d')
            if artist and album:
                return {
                    "artist": artist,
                    "album": album,
                    "source": "Bandcamp Daily",
                    "excerpt": "",
                    "score": None,
                }
        return None
    except Exception:
        return None
