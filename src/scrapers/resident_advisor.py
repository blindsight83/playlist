"""
Resident Advisor scraper — uses RA's GraphQL API to fetch recent album reviews.
Endpoint: https://ra.co/graphql
"""
import requests

GRAPHQL_URL = "https://ra.co/graphql"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "Chrome/120.0.0.0 Safari/537.36",
    "Content-Type": "application/json",
    "Referer": "https://ra.co/reviews/albums",
    "Origin": "https://ra.co",
}

QUERY = """
query AlbumReviews($limit: Int) {
  reviews(limit: $limit, type: ALBUM) {
    title
    blurb
    recommended
    artists { name }
    labels { name }
  }
}
"""


def scrape(limit: int = 20) -> list[dict]:
    candidates: list[dict] = []
    try:
        r = requests.post(
            GRAPHQL_URL,
            json={"query": QUERY, "variables": {"limit": limit}},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        for item in data.get("data", {}).get("reviews", []):
            candidate = _parse_item(item)
            if candidate:
                candidates.append(candidate)
    except Exception as e:
        print(f"[resident_advisor] error: {e}")

    print(f"[resident_advisor] {len(candidates)} candidates")
    return candidates


def _parse_item(item: dict) -> dict | None:
    try:
        raw_title = item.get("title", "") or ""
        blurb = item.get("blurb", "") or ""
        recommended = item.get("recommended", False)
        artists = item.get("artists", []) or []

        # title is typically "Artist - Album Title" or "Artist & Artist2 - Album"
        artist_name = ", ".join(a.get("name", "") for a in artists if a.get("name"))
        album = ""

        if " - " in raw_title:
            parts = raw_title.split(" - ", 1)
            if not artist_name:
                artist_name = parts[0].strip()
            album = parts[1].strip()
        else:
            album = raw_title.strip()

        if not artist_name or not album:
            return None

        excerpt = blurb.strip()[:300]
        if recommended:
            excerpt = f"[Recommended] {excerpt}".strip()

        return {
            "artist": artist_name,
            "album": album,
            "source": "Resident Advisor",
            "excerpt": excerpt,
            "score": None,
        }
    except Exception:
        return None
