#!/usr/bin/env python3
"""
Weekly music curation pipeline.
Scrapes music publications, curates 20 albums via Claude, updates Spotify, sends newsletter.
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(override=True)  # .env takes precedence locally; GitHub Actions uses secrets

from datetime import date
from src.scrapers import pitchfork, the_wire, resident_advisor, bandcamp_daily, rumore
from src import curate, spotify, newsletter


def main():
    print("=== Weekly Music Curation ===\n")

    # 1. Scrape candidates
    print("--- Scraping publications ---")
    candidates = []
    for mod in [pitchfork, bandcamp_daily, the_wire, resident_advisor, rumore]:
        try:
            results = mod.scrape()
            candidates.extend(results)
        except Exception as e:
            print(f"[scraper {mod.__name__}] failed: {e}")

    print(f"\nTotal candidates: {len(candidates)}\n")
    if len(candidates) < 5:
        print("ERROR: too few candidates scraped. Aborting.", file=sys.stderr)
        sys.exit(1)

    # 2. Curate with Claude
    print("--- Curating with Claude ---")
    curation_output = curate.curate(candidates)
    print(f"Curation output: {len(curation_output)} chars\n")

    # Save output locally for debugging / archive
    output_path = Path("output") / f"curation_{_today()}.md"
    output_path.parent.mkdir(exist_ok=True)
    output_path.write_text(curation_output)
    print(f"Saved to {output_path}\n")

    # 3. Enrich albums from Spotify (covers, links, label) — only needs client credentials
    enrichment = {}
    if os.environ.get("SPOTIFY_CLIENT_ID"):
        print("--- Enriching albums from Spotify ---")
        try:
            enrichment = spotify.enrich_albums(curation_output)
            print(f"Enriched {len(enrichment)} albums\n")
        except Exception as e:
            print(f"[spotify enrich] error: {e}\n")

    # 4. Update Spotify playlist (requires refresh token)
    if os.environ.get("SPOTIFY_REFRESH_TOKEN") and os.environ.get("SPOTIFY_CLIENT_ID"):
        print("--- Updating Spotify playlist ---")
        try:
            added = spotify.update_playlist(curation_output)
            print(f"Added {added} tracks\n")
        except Exception as e:
            print(f"[spotify] error: {e}\n")
    else:
        print("--- Spotify playlist skipped (SPOTIFY_REFRESH_TOKEN not set) ---\n")

    # 5. Build and save HTML preview
    print("--- Building HTML ---")
    week_date = date.today().strftime("%B %d, %Y")
    html = newsletter.build_html(curation_output, week_date, enrichment)
    preview_path = Path("output") / f"preview_{_today()}.html"
    preview_path.write_text(html)
    # Also write a stable preview.html for local use
    (Path("output") / "preview.html").write_text(html)
    print(f"Saved to {preview_path}\n")

    # 6. Send newsletter
    if os.environ.get("SENDGRID_API_KEY"):
        print("--- Sending newsletter ---")
        try:
            newsletter.send(curation_output, enrichment)
        except Exception as e:
            print(f"[newsletter] error: {e}\n")
    else:
        print("--- Newsletter skipped (SENDGRID_API_KEY not set) ---\n")

    print("=== Done ===")


def _today() -> str:
    from datetime import date
    return date.today().isoformat()


if __name__ == "__main__":
    main()
