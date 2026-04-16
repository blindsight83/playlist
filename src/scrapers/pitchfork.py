"""
Pitchfork scraper — parses the reviews/albums and reviews/best/albums pages.
The pages are server-side rendered with CSS module class names, but the
review data follows a consistent text pattern:
    Genre | Album Title | Artist Name | By | Reviewer | Date
"""
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "Chrome/120.0.0.0 Safari/537.36",
}


def scrape(limit: int = 30) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    for url, is_bnm in [
        ("https://pitchfork.com/reviews/best/albums/", True),
        ("https://pitchfork.com/reviews/albums/", False),
    ]:
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "lxml")
            items = soup.select('[class*="SummaryItemWrapper"]')
            for item in items:
                candidate = _parse_item(item, bnm=is_bnm)
                if candidate:
                    key = candidate["album"] + candidate["artist"]
                    if key not in seen:
                        candidates.append(candidate)
                        seen.add(key)
                if len(candidates) >= limit:
                    break
        except Exception as e:
            print(f"[pitchfork] error fetching {url}: {e}")

    print(f"[pitchfork] {len(candidates)} candidates")
    return candidates


def _parse_item(item, bnm: bool = False) -> dict | None:
    try:
        parts = [p.strip() for p in item.get_text(separator=" | ", strip=True).split(" | ") if p.strip()]
        # Pattern: Genre | Album | Artist | By | Reviewer | Date
        if "By" not in parts or len(parts) < 4:
            return None
        by_idx = parts.index("By")
        if by_idx < 2:
            return None
        album = parts[1]
        artist = parts[by_idx - 1]
        if not album or not artist or album == artist:
            return None
        source = "Pitchfork BNM" if bnm else "Pitchfork"
        excerpt = f"[Best New Music] " if bnm else ""
        return {
            "artist": artist,
            "album": album,
            "source": source,
            "excerpt": excerpt,
            "score": None,
        }
    except Exception:
        return None
