"""
Newsletter formatter and sender.
Converts Claude's markdown curation output into a styled HTML email
and sends it via Gmail SMTP (smtplib — no external service needed).
"""
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import date


CATEGORY_COLORS = {
    "CORE": "#4a9eff",
    "BRIDGE": "#9b59b6",
    "EXPLORATION": "#2ecc71",
}

CATEGORY_LABELS = {
    "CORE": "Core",
    "BRIDGE": "Bridge",
    "EXPLORATION": "Exploration",
}


def _md(text: str) -> str:
    """Minimal markdown → inline HTML."""
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text


def _extract_field(body: str, label: str) -> str:
    """Extract content under a **Label** heading until the next **heading** or end."""
    pattern = re.compile(
        rf"\*\*{re.escape(label)}\*\*\s*\n(.*?)(?=\n\*\*|\Z)", re.DOTALL
    )
    m = pattern.search(body)
    return m.group(1).strip() if m else ""


def _extract_location(body: str) -> str:
    """
    Extract the **Location:** field and return a clean 'City, Country' string.
    Strips parenthetical notes, takes the first city if multiple are listed,
    and drops placeholder values like '[Location unclear...]'.
    """
    m = re.search(r"\*\*Location:\*\*\s*(.+)", body)
    if not m:
        return ""
    raw = m.group(1).strip().rstrip(".")
    # Drop unclear or non-geographic placeholders
    if raw.startswith("[") or any(w in raw.lower() for w in ("unclear", "global", "international", "various")):
        return ""
    # Remove parenthetical notes: "Naarm (Melbourne), Australia" → "Naarm, Australia"
    raw = re.sub(r"\s*\([^)]+\)", "", raw).strip()
    # Take first city if slash-separated
    if " / " in raw:
        raw = raw.split(" / ")[0].strip()
    # Clean trailing commas/dashes
    raw = raw.strip(" ,/–—")
    return raw if raw else ""


def _extract_source(body: str) -> str:
    """Extract the **Source:** field."""
    m = re.search(r"\*\*Source:\*\*\s*(.+)", body)
    if not m:
        return ""
    return m.group(1).strip().strip('"').strip("'")


def parse_sections(curation_text: str) -> dict:
    sections: dict[str, list[str]] = {"CORE": [], "BRIDGE": [], "EXPLORATION": []}
    current_section = None
    # Match section headers at any heading level: ## CORE, ### CORE, etc.
    section_pattern = re.compile(r"^#{2,4}\s+(CORE|BRIDGE|EXPLORATION)\s*$", re.MULTILINE)
    # Match album entries: ##/###/#### with optional "N. " numbering
    album_pattern = re.compile(r"^#{2,4}\s+(?:\d+\.\s+)?(?!CORE|BRIDGE|EXPLORATION)", re.MULTILINE)

    parts = section_pattern.split(curation_text)
    for part in parts:
        stripped = part.strip()
        if stripped in sections:
            current_section = stripped
        elif current_section and stripped:
            for block in album_pattern.split(stripped):
                block = block.strip()
                if block:
                    sections[current_section].append("### " + block)

    # Deduplicate: keep only the first occurrence of each title across all sections
    seen_titles: set[str] = set()
    for sec in sections:
        unique = []
        for block in sections[sec]:
            first_line = block.splitlines()[0].replace("### ", "").strip()
            if first_line not in seen_titles:
                unique.append(block)
                seen_titles.add(first_line)
        sections[sec] = unique

    return sections


def render_album_card(block: str, category: str, enrichment: dict, index: int = 0) -> str:
    lines = block.strip().splitlines()
    if not lines:
        return ""

    # First line: ### Artist — Album Title
    title_line = lines[0].replace("### ", "").strip()
    body = "\n".join(lines[1:]).strip()

    color = CATEGORY_COLORS.get(category, "#4a9eff")
    cat_label = CATEGORY_LABELS.get(category, category)

    # Extract structured fields
    artist_bio  = _extract_field(body, "Artist")
    about       = _extract_field(body, "About the album")
    why         = _extract_field(body, "Why for you")
    signals_raw = _extract_field(body, "Signals")
    source      = _extract_source(body)

    # Fallback: handle label variations Claude uses
    if not about:
        about = (_extract_field(body, "About the project")
              or _extract_field(body, "About the compilation")
              or _extract_field(body, "Summary"))
    if not why:
        why = _extract_field(body, "Why this was picked for you")

    # Parse signal tags
    cultural  = re.search(r"- Cultural:\s*(.+)", signals_raw)
    aesthetic = re.search(r"- Aesthetic:\s*(.+)", signals_raw)
    critical  = re.search(r"- Critical:\s*(.+)", signals_raw)

    tags_html = ""
    if cultural:
        for tag in [t.strip().strip('"') for t in cultural.group(1).split(",") if t.strip()]:
            tags_html += f'<span class="tag cultural">{tag}</span>'
    if aesthetic:
        for tag in [t.strip().strip('"') for t in aesthetic.group(1).split(",") if t.strip()]:
            tags_html += f'<span class="tag aesthetic">{tag}</span>'
    if critical:
        tags_html += f'<span class="tag critical">{critical.group(1).strip()}</span>'

    # Spotify enrichment — match against "Artist — Album" keys
    clean_title = re.sub(r"^\d+\.\s+", "", title_line).strip()
    enrich = enrichment.get(clean_title) or enrichment.get(title_line) or {}
    cover_url    = enrich.get("cover_url", "")
    spotify_url  = enrich.get("spotify_url", "")
    label        = enrich.get("label", "")
    release_year = enrich.get("release_year", "")

    # Cover image block
    cover_html = ""
    if cover_url:
        cover_html = f'<img src="{cover_url}" class="cover" alt="Album cover">'
    else:
        cover_html = '<div class="cover cover-placeholder"></div>'

    # Spotify button
    spotify_html = ""
    if spotify_url:
        spotify_html = f'<a href="{spotify_url}" class="spotify-btn" target="_blank"><span class="spotify-icon">&#9654;</span> Listen</a>'

    # Source badge
    source_html = ""
    if source:
        source_html = f'<span class="source-badge">{source}</span>'

    # Label + year + location line
    location = _extract_location(body)
    meta_parts = [p for p in [label, release_year, location] if p]
    meta_html = ""
    if meta_parts:
        meta_html = f'<div class="album-meta">{" &middot; ".join(meta_parts)}</div>'

    # Index number
    num_str = str(index).zfill(2)

    # Artist bio block
    artist_html = ""
    if artist_bio:
        artist_html = f'''<div class="field-block artist-bio">
          <span class="field-label">Artist</span>
          <p>{_md(artist_bio)}</p>
        </div>'''

    # About block
    about_html = ""
    if about:
        about_html = f'''<div class="field-block about">
          <span class="field-label">About the album</span>
          <p>{_md(about)}</p>
        </div>'''

    # Why block
    why_html = ""
    if why:
        why_html = f'''<div class="field-block why">
          <span class="field-label">Why for you</span>
          <p>{_md(why)}</p>
        </div>'''

    return f"""
    <div class="album-card" id="album-{index}">
      <div class="album-number">{num_str}</div>
      <div class="album-body">
        <div class="album-header">
          <div class="cover-wrap">{cover_html}</div>
          <div class="album-header-right">
            <div class="album-top-row">
              <div class="badge-row">
                <span class="category-badge" style="color:{color}; border-color:{color}40;">{cat_label}</span>
                {source_html}
              </div>
              {spotify_html}
            </div>
            <h3 class="album-title">{_md(title_line)}</h3>
            {meta_html}
            {f'<div class="tags">{tags_html}</div>' if tags_html else ''}
          </div>
        </div>
        <div class="album-content">
          {artist_html}
          {about_html}
          {why_html}
        </div>
      </div>
    </div>
    """


def build_html(curation_text: str, week_date: str, enrichment: dict | None = None) -> str:
    if enrichment is None:
        enrichment = {}
    sections = parse_sections(curation_text)

    sections_html = ""
    global_index = 1
    for section_name in ["CORE", "BRIDGE", "EXPLORATION"]:
        albums = sections.get(section_name, [])
        if not albums:
            continue
        color = CATEGORY_COLORS[section_name]
        desc = {
            "CORE": "Strong cultural and aesthetic alignment.",
            "BRIDGE": "Meaningful extension beyond core territory.",
            "EXPLORATION": "Low alignment, high cultural or critical relevance.",
        }[section_name]

        cards = ""
        for b in albums:
            cards += render_album_card(b, section_name, enrichment, global_index)
            global_index += 1

        sections_html += f"""
        <div class="section" id="section-{section_name.lower()}">
          <div class="section-header">
            <div class="section-label-wrap">
              <span class="section-rule" style="background:{color}"></span>
              <h2 class="section-title" style="color:{color}">{section_name}</h2>
              <span class="section-count">{len(albums)}</span>
            </div>
            <p class="section-desc">{desc}</p>
          </div>
          <div class="album-list">
            {cards}
          </div>
        </div>
        """

    css = _get_css()

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Weekly Curation — {week_date}</title>
<style>
{css}
</style>
</head>
<body>
<div class="wrapper">
  <header class="masthead">
    <div class="masthead-left">
      <div class="masthead-kicker">Weekly Music Intelligence</div>
      <h1 class="masthead-title">Curation</h1>
    </div>
    <div class="masthead-right">
      <div class="masthead-date">{week_date}</div>
      <div class="masthead-count">20 albums selected</div>
      <div class="masthead-sources">Pitchfork &middot; The Wire &middot; RA &middot; Bandcamp</div>
    </div>
  </header>
  <div class="toc">
    <span class="toc-label">This week:</span>
    <span class="toc-item" style="color:#4a9eff">&#9632; 7 Core</span>
    <span class="toc-sep">/</span>
    <span class="toc-item" style="color:#9b59b6">&#9632; 7 Bridge</span>
    <span class="toc-sep">/</span>
    <span class="toc-item" style="color:#2ecc71">&#9632; 6 Exploration</span>
  </div>
  {sections_html}
  <footer class="footer">
    <div class="footer-inner">
      <span>Weekly Curation</span>
      <span class="footer-dot">·</span>
      <span>Pitchfork · The Wire · Resident Advisor · Bandcamp Daily</span>
      <span class="footer-dot">·</span>
      <span>{week_date}</span>
    </div>
  </footer>
</div>
</body>
</html>"""


def _get_css() -> str:
    return """
  /* ─── Reset ─────────────────────────────────────────────── */
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  /* ─── Base ───────────────────────────────────────────────── */
  body {
    font-family: 'Times New Roman', Times, Georgia, serif;
    background: #111111;
    color: #d8d4cc;
    line-height: 1.6;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
  }

  .wrapper {
    max-width: 740px;
    margin: 0 auto;
    padding: 0 28px 80px;
    background: #111111;
  }

  /* ─── Masthead ───────────────────────────────────────────── */
  .masthead {
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    padding: 56px 0 28px;
    border-bottom: 2px solid #e8e4dc;
    margin-bottom: 0;
    gap: 24px;
  }

  .masthead-kicker {
    font-family: 'Courier New', Courier, monospace;
    font-size: 10px;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: #666;
    margin-bottom: 10px;
  }

  .masthead-title {
    font-family: 'Times New Roman', Times, Georgia, serif;
    font-size: 52px;
    font-weight: normal;
    color: #ffffff;
    letter-spacing: -0.02em;
    line-height: 1;
  }

  .masthead-right {
    text-align: right;
    flex-shrink: 0;
  }

  .masthead-date {
    font-family: 'Courier New', Courier, monospace;
    font-size: 12px;
    color: #e8e4dc;
    letter-spacing: 0.08em;
    margin-bottom: 5px;
  }

  .masthead-count {
    font-family: 'Courier New', Courier, monospace;
    font-size: 10px;
    color: #666;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 5px;
  }

  .masthead-sources {
    font-family: 'Courier New', Courier, monospace;
    font-size: 10px;
    color: #555;
    letter-spacing: 0.06em;
  }

  /* ─── TOC bar ─────────────────────────────────────────────── */
  .toc {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 16px 0;
    border-bottom: 1px solid #252525;
    margin-bottom: 60px;
    font-family: 'Courier New', Courier, monospace;
    font-size: 11px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
  }

  .toc-label {
    color: #555;
    margin-right: 4px;
  }

  .toc-item { font-weight: bold; }

  .toc-sep { color: #333; }

  /* ─── Section ─────────────────────────────────────────────── */
  .section {
    margin-bottom: 72px;
  }

  .section-header {
    margin-bottom: 36px;
    padding-bottom: 18px;
    border-bottom: 1px solid #222;
  }

  .section-label-wrap {
    display: flex;
    align-items: center;
    gap: 14px;
    margin-bottom: 8px;
  }

  .section-rule {
    display: inline-block;
    width: 28px;
    height: 2px;
    flex-shrink: 0;
  }

  .section-title {
    font-family: 'Courier New', Courier, monospace;
    font-size: 11px;
    font-weight: normal;
    letter-spacing: 0.3em;
    text-transform: uppercase;
  }

  .section-count {
    font-family: 'Courier New', Courier, monospace;
    font-size: 10px;
    color: #444;
    letter-spacing: 0.1em;
  }

  .section-desc {
    font-family: 'Courier New', Courier, monospace;
    font-size: 11px;
    color: #555;
    letter-spacing: 0.04em;
    padding-left: 42px;
  }

  /* ─── Album card ──────────────────────────────────────────── */
  .album-card {
    display: flex;
    gap: 0;
    padding: 36px 0;
    border-bottom: 1px solid #1e1e1e;
    position: relative;
  }

  .album-number {
    font-family: 'Courier New', Courier, monospace;
    font-size: 10px;
    color: #3a3a3a;
    letter-spacing: 0.08em;
    padding-top: 4px;
    width: 36px;
    flex-shrink: 0;
  }

  .album-body {
    flex: 1;
    min-width: 0;
  }

  /* ─── Album header ────────────────────────────────────────── */
  .album-header {
    display: flex;
    gap: 20px;
    margin-bottom: 24px;
    align-items: flex-start;
  }

  .cover-wrap {
    flex-shrink: 0;
  }

  .cover {
    width: 110px;
    height: 110px;
    object-fit: cover;
    display: block;
    border-radius: 0;
    background: #1a1a1a;
  }

  .cover-placeholder {
    width: 110px;
    height: 110px;
    background: #1a1a1a;
    border: 1px solid #252525;
    display: block;
  }

  .album-header-right {
    flex: 1;
    min-width: 0;
  }

  .album-top-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 10px;
    gap: 8px;
  }

  .badge-row {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
  }

  .album-title {
    font-family: 'Times New Roman', Times, Georgia, serif;
    font-size: 21px;
    font-weight: normal;
    color: #ffffff;
    line-height: 1.25;
    letter-spacing: -0.01em;
    margin-bottom: 10px;
  }

  /* ─── Badges ──────────────────────────────────────────────── */
  .category-badge {
    font-family: 'Courier New', Courier, monospace;
    font-size: 9px;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    padding: 3px 9px;
    border: 1px solid;
    background: transparent;
    white-space: nowrap;
    font-weight: normal;
  }

  .source-badge {
    font-family: 'Courier New', Courier, monospace;
    font-size: 9px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #666;
    border: 1px solid #2a2a2a;
    padding: 3px 9px;
    background: transparent;
    white-space: nowrap;
  }

  /* ─── Meta ────────────────────────────────────────────────── */
  .album-meta {
    font-family: 'Courier New', Courier, monospace;
    font-size: 11px;
    color: #666;
    letter-spacing: 0.05em;
    margin-bottom: 12px;
  }

  /* ─── Tags ────────────────────────────────────────────────── */
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    margin-top: 4px;
  }

  .tag {
    font-family: 'Courier New', Courier, monospace;
    font-size: 10px;
    padding: 2px 8px;
    letter-spacing: 0.04em;
    white-space: nowrap;
    border: 1px solid;
  }

  .tag.cultural  {
    color: #6ab880;
    border-color: #2a4a32;
    background: transparent;
  }

  .tag.aesthetic {
    color: #7a8ed4;
    border-color: #2a2e52;
    background: transparent;
  }

  .tag.critical  {
    color: #cc7070;
    border-color: #4a2222;
    background: transparent;
  }

  /* ─── Spotify ─────────────────────────────────────────────── */
  .spotify-btn {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-family: 'Courier New', Courier, monospace;
    font-size: 10px;
    color: #1db954;
    border: 1px solid #1db95450;
    padding: 5px 12px;
    text-decoration: none;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    white-space: nowrap;
    flex-shrink: 0;
  }

  .spotify-icon {
    font-size: 9px;
  }

  /* ─── Content fields ──────────────────────────────────────── */
  .album-content {
    display: flex;
    flex-direction: column;
    gap: 22px;
  }

  .field-block {}

  .field-label {
    display: block;
    font-family: 'Courier New', Courier, monospace;
    font-size: 9px;
    letter-spacing: 0.2em;
    text-transform: uppercase;
    color: #555;
    margin-bottom: 8px;
  }

  .field-block p {
    font-family: 'Times New Roman', Times, Georgia, serif;
    font-size: 15px;
    line-height: 1.75;
    color: #a8a49c;
  }

  .field-block.artist-bio p {
    color: #7a7670;
    font-size: 14px;
  }

  .field-block.about p {
    color: #b0aca4;
  }

  .field-block.why {
    padding: 18px 22px;
    border-left: 2px solid #2a2a2a;
    background: #161616;
  }

  .field-block.why .field-label { color: #666; }

  .field-block.why p {
    color: #c4beb6;
    font-style: italic;
    font-size: 15px;
    line-height: 1.75;
  }

  /* ─── Footer ──────────────────────────────────────────────── */
  .footer {
    margin-top: 64px;
    padding-top: 20px;
    border-top: 2px solid #e8e4dc;
  }

  .footer-inner {
    font-family: 'Courier New', Courier, monospace;
    font-size: 10px;
    color: #444;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    display: flex;
    gap: 12px;
    align-items: center;
    flex-wrap: wrap;
  }

  .footer-dot { color: #2a2a2a; }
"""


def send(curation_text: str, enrichment: dict | None = None) -> None:
    week_date = date.today().strftime("%B %d, %Y")
    html = build_html(curation_text, week_date, enrichment)

    smtp_user = os.environ["SMTP_USER"]          # Gmail login address
    smtp_pass = os.environ["SMTP_PASS"].replace(" ", "")  # strip spaces from app password
    recipient = os.environ["RECIPIENT_EMAIL"]
    sender    = os.environ.get("SMTP_FROM", smtp_user)  # display From address

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Weekly Curation — {week_date}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, recipient, msg.as_string())

    print(f"[newsletter] sent from {sender} to {recipient}")
