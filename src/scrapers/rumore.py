"""
Rumore scraper — fetches recent album reviews from rumore.it (Italian music magazine).

Note: rumore.it uses a self-signed certificate. We disable SSL verification
and suppress the InsecureRequestWarning.
"""
import warnings
import requests
from bs4 import BeautifulSoup
from urllib3.exceptions import InsecureRequestWarning

warnings.filterwarnings("ignore", category=InsecureRequestWarning)

BASE_URL = "https://www.rumore.it"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Possible review section paths — try each in order
REVIEW_PATHS = [
    "/categoria/recensioni",
    "/categoria/recensioni/",
    "/sezione/recensioni",
    "/tag/recensioni",
    "/",
]


def scrape(limit: int = 20) -> list[dict]:
    candidates: list[dict] = []
    seen: set[str] = set()

    for path in REVIEW_PATHS:
        url = BASE_URL + path
        try:
            r = requests.get(url, headers=HEADERS, timeout=15, verify=False)
            if r.status_code != 200 or len(r.text) < 200:
                continue

            soup = BeautifulSoup(r.text, "lxml")
            articles = soup.select("article, .post, li.post, .entry, .recensione")

            if not articles:
                continue

            for article in articles[:limit * 2]:
                candidate = _parse_article(article)
                if candidate:
                    key = candidate["album"] + candidate["artist"]
                    if key not in seen:
                        candidates.append(candidate)
                        seen.add(key)
                if len(candidates) >= limit:
                    break
            if candidates:
                break
        except Exception as e:
            print(f"[rumore] error at {url}: {e}")

    print(f"[rumore] {len(candidates)} candidates")
    return candidates


def _parse_article(article) -> dict | None:
    try:
        heading = article.select_one("h2, h3, h4, .entry-title, .title")
        if not heading:
            return None
        text = heading.get_text(strip=True)
        artist, album = _split_title(text)
        if not artist or not album:
            return None

        excerpt_el = article.select_one("p, .entry-summary, .excerpt")
        excerpt = excerpt_el.get_text(strip=True)[:300] if excerpt_el else ""

        score = None
        score_el = article.select_one(".voto, .rating, .score, [class*='voto']")
        if score_el:
            score = score_el.get_text(strip=True)

        return {
            "artist": artist,
            "album": album,
            "source": "Rumore",
            "excerpt": excerpt,
            "score": score,
        }
    except Exception:
        return None


def _split_title(title: str) -> tuple[str, str]:
    for sep in [" \u2013 ", " \u2014 ", ": ", " - "]:
        if sep in title:
            parts = title.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return "", title.strip()
