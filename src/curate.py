"""
Curation via Claude API.
Assembles the prompt from goal.md + TasteGraph.md + scraped candidates,
calls claude-sonnet-4-6 with prompt caching on the stable system context.
"""
import os
from pathlib import Path
from dotenv import load_dotenv
import anthropic

load_dotenv(override=True)

ROOT = Path(__file__).parent.parent

# Markers that signal the start of the final structured output
_OUTPUT_MARKERS = [
    "## STEP 3 — OUTPUT",
    "## STEP 3 — FINAL OUTPUT",
    "## FINAL OUTPUT",
    "## FINAL SELECTION",
    "## CORE",
]


def _extract_final_output(text: str) -> str:
    """
    Strip away any analysis preamble and return only the final output block.
    Looks specifically for '## CORE' (top-level section heading, not subsection).
    """
    import re
    # Must be exactly ## CORE (2 hashes), not ### CORE (analysis subsection)
    m = re.search(r"^## CORE\b", text, re.MULTILINE)
    if m:
        body = text[m.start():]
    else:
        # Fallback: split on known step markers
        body = text
        for marker in _OUTPUT_MARKERS:
            if marker in text:
                body = text.split(marker, 1)[1].strip()
                break

    # Strip any trailing verification / summary sections Haiku appends after the albums
    tail_markers = [
        "## STEP 4", "## GLOBAL", "## NOTE", "## RECOMMENDED",
        "## **RECOMMENDED", "## VERIFICATION", "## SUMMARY",
        "## FINAL NOTES", "## SELECTION NOTES",
    ]
    for tail_marker in tail_markers:
        if tail_marker in body:
            body = body.split(tail_marker, 1)[0].rstrip()
            break

    return body
GOAL_PATH = ROOT / "goal.md"
TASTE_GRAPH_PATH = ROOT / "TasteGraph.md"


def format_candidates(candidates: list[dict]) -> str:
    lines = []
    for i, c in enumerate(candidates, 1):
        score_str = f" [{c['score']}/10]" if c.get("score") else ""
        lines.append(f"{i}. **{c['artist']} — {c['album']}**")
        lines.append(f"   Source: {c['source']}{score_str}")
        if c.get("excerpt"):
            lines.append(f"   > {c['excerpt']}")
        lines.append("")
    return "\n".join(lines)


def curate(candidates: list[dict]) -> str:
    """
    Returns Claude's full curation output as a markdown string.
    Uses prompt caching on TasteGraph (stable) to reduce cost across weekly runs.
    """
    taste_graph = TASTE_GRAPH_PATH.read_text()
    goal_template = GOAL_PATH.read_text()

    candidates_text = format_candidates(candidates)

    # Fill in the goal template
    prompt = goal_template.replace("[PASTE TASTE GRAPH HERE]", taste_graph).replace(
        "[PASTE HERE]", candidates_text
    )

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # System prompt with caching — TasteGraph is stable week to week
    system_content = [
        {
            "type": "text",
            "text": (
                "You are a music curation assistant with deep knowledge of scenes, lineages, "
                "and critical discourse. You produce carefully reasoned, specific, and honest "
                "recommendations grounded in the user's taste profile and the critical texts provided."
            ),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    # The full prompt (TasteGraph embedded) also gets cached since it barely changes
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=16000,
        system=system_content,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            }
        ],
    )

    usage = message.usage
    print(
        f"[curate] tokens — input: {usage.input_tokens}, output: {usage.output_tokens}, "
        f"cache_read: {getattr(usage, 'cache_read_input_tokens', 0)}, "
        f"cache_write: {getattr(usage, 'cache_creation_input_tokens', 0)}"
    )

    return _extract_final_output(message.content[0].text)
