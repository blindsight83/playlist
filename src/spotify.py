"""
Spotify integration.
- enrich_albums(): fetch cover art, Spotify URL, label for newsletter rendering
- update_playlist(): append representative tracks to master playlist
"""
import os
import re
import spotipy
from spotipy.oauth2 import SpotifyOAuth, SpotifyClientCredentials


TRACKS_PER_ALBUM = 1


def get_search_client() -> spotipy.Spotify:
    """Client credentials client — for search/enrichment, no user auth needed."""
    return spotipy.Spotify(auth_manager=SpotifyClientCredentials(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
    ))


def _search_album(sp: spotipy.Spotify, artist: str, album: str) -> dict | None:
    """
    Search Spotify and return the full album object (with label), or None.
    Search returns simplified objects without label — we fetch the full object by ID.
    """
    for query in [f'album:"{album}" artist:"{artist}"', f"{album} {artist}"]:
        results = sp.search(q=query, type="album", limit=3)
        items = results.get("albums", {}).get("items", [])
        if items:
            # Fetch full album object so we get the label field
            return sp.album(items[0]["id"])
    return None


def enrich_albums(curation_text: str) -> dict[str, dict]:
    """
    For each album in the curation output, fetch from Spotify:
      cover_url, spotify_url, label, release_year

    Returns a dict keyed by "Artist — Album":
      { "Artist — Album": { cover_url, spotify_url, label, release_year }, ... }
    """
    sp = get_search_client()
    albums = parse_albums_from_curation(curation_text)
    enrichment: dict[str, dict] = {}

    for info in albums:
        key = f"{info['artist']} — {info['album']}"
        album_obj = _search_album(sp, info["artist"], info["album"])
        if album_obj:
            images = album_obj.get("images", [])
            cover_url = images[0]["url"] if images else ""
            enrichment[key] = {
                "cover_url": cover_url,
                "spotify_url": album_obj.get("external_urls", {}).get("spotify", ""),
                "label": album_obj.get("label", ""),
                "release_year": (album_obj.get("release_date") or "")[:4],
            }
            print(f"  [enrich] {key} → {enrichment[key]['label']} {enrichment[key]['release_year']}")
        else:
            enrichment[key] = {"cover_url": "", "spotify_url": "", "label": "", "release_year": ""}
            print(f"  [enrich] not found: {key}")

    return enrichment


def _parse_playlist_id(value: str) -> str:
    """Accept either a bare ID or a full Spotify URL/URI."""
    m = re.search(r"playlist[/:]([A-Za-z0-9]+)", value)
    return m.group(1) if m else value.strip()


def get_client() -> spotipy.Spotify:
    auth = SpotifyOAuth(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        redirect_uri="http://127.0.0.1:3000",
        scope="playlist-modify-public playlist-modify-private playlist-read-private",
    )
    # Inject the refresh token directly so no browser flow is needed in CI
    token_info = auth.refresh_access_token(os.environ["SPOTIFY_REFRESH_TOKEN"])
    return spotipy.Spotify(auth=token_info["access_token"])


def get_existing_track_uris(sp: spotipy.Spotify, playlist_id: str) -> set[str]:
    uris: set[str] = set()
    results = sp.playlist_tracks(playlist_id, fields="items(track(uri)),next")
    while results:
        for item in results.get("items", []):
            if item and item.get("track") and item["track"].get("uri"):
                uris.add(item["track"]["uri"])
        results = sp.next(results) if results.get("next") else None
    return uris


def find_tracks_for_album(sp: spotipy.Spotify, artist: str, album: str) -> list[str]:
    """Returns up to TRACKS_PER_ALBUM Spotify track URIs for the given album."""
    query = f'album:"{album}" artist:"{artist}"'
    results = sp.search(q=query, type="album", limit=3)
    albums = results.get("albums", {}).get("items", [])

    if not albums:
        # Looser search
        query2 = f"{album} {artist}"
        results2 = sp.search(q=query2, type="album", limit=3)
        albums = results2.get("albums", {}).get("items", [])

    if not albums:
        print(f"  [spotify] not found: {artist} — {album}")
        return []

    # Pick the best match (first result)
    album_id = albums[0]["id"]
    tracks = sp.album_tracks(album_id, limit=TRACKS_PER_ALBUM)
    uris = [t["uri"] for t in tracks.get("items", []) if t.get("uri")]
    return uris[:TRACKS_PER_ALBUM]


def parse_albums_from_curation(curation_text: str) -> list[dict]:
    """
    Extract artist/album pairs from Claude's markdown output.
    Handles heading levels ##/###/#### and optional numbering like '1. Artist — Album'.
    """
    albums = []
    # Match: any heading level, optional "N. " prefix, Artist — Album
    pattern = re.compile(
        r"^#{2,4}\s+(?:\d+\.\s+)?(.+?)\s+[—–-]+\s+(.+)$", re.MULTILINE
    )
    seen: set[str] = set()
    for match in pattern.finditer(curation_text):
        artist = match.group(1).strip()
        album  = match.group(2).strip()
        # Skip section headings that leaked through (CORE, BRIDGE, EXPLORATION)
        if artist.upper() in ("CORE", "BRIDGE", "EXPLORATION"):
            continue
        key = artist + album
        if key not in seen:
            albums.append({"artist": artist, "album": album})
            seen.add(key)
    return albums


def update_playlist(curation_text: str) -> int:
    """
    Finds tracks for all curated albums and appends new ones to the master playlist.
    Returns the number of tracks added.
    """
    playlist_id = _parse_playlist_id(os.environ["SPOTIFY_PLAYLIST_ID"])
    sp = get_client()

    albums = parse_albums_from_curation(curation_text)
    print(f"[spotify] found {len(albums)} albums to process")

    existing_uris = get_existing_track_uris(sp, playlist_id)
    print(f"[spotify] playlist has {len(existing_uris)} existing tracks")

    new_uris: list[str] = []
    for album_info in albums:
        uris = find_tracks_for_album(sp, album_info["artist"], album_info["album"])
        added = [u for u in uris if u not in existing_uris]
        if added:
            print(f"  + {album_info['artist']} — {album_info['album']}: {len(added)} track(s)")
            new_uris.extend(added)
        else:
            print(f"  ~ {album_info['artist']} — {album_info['album']}: already in playlist or not found")

    if new_uris:
        # Spotify allows max 100 tracks per request
        for i in range(0, len(new_uris), 100):
            sp.playlist_add_items(playlist_id, new_uris[i:i + 100])
        print(f"[spotify] added {len(new_uris)} new tracks to playlist")
    else:
        print("[spotify] no new tracks to add")

    return len(new_uris)
