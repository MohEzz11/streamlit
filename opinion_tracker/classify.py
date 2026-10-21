"""Stance classification: Claude when an API key is available, rules otherwise.

Each post can mention several tickers, and each mention gets one stance:
  bullish     the author expresses a positive view or position
  bearish     the author expresses a negative view, short, or exit
  neutral     the author takes no clear side (watching, asking, reporting)
  background  the ticker is only named in passing (a list, a comparison)
"""

import json
import re

import anthropic

DEFAULT_MODEL = "claude-opus-5-5"
STANCES = ["bullish", "bearish", "neutral", "background"]
BATCH_SIZE = 25

SYSTEM_PROMPT = """You extract stock opinions from an investment analyst's social media posts.

For every post, list each publicly traded company the author refers to, by
cashtag ($LITE), ticker, or company name. Use the primary listing ticker in
upper case without an exchange suffix (Sivers Photonics -> SIVE, Soitec -> SOI,
Taiwan Semiconductor -> TSM). Skip indexes, ETFs, crypto coins and private
companies.

Give each mention exactly one stance, judged from the author's own view, not
from the news being quoted:
- bullish: the author is positive, owns it, is adding, or argues upside.
- bearish: the author is negative, short, selling, or argues downside.
- neutral: the author discusses it without taking a side.
- background: the ticker is only named in passing, in a list or comparison,
  with no view on it.

Read sarcasm and replies carefully: mocking short sellers of a stock is
bullish on that stock. confidence is your probability (0 to 1) that the
stance is right. rationale is one short sentence quoting or paraphrasing the
words that justify the stance. risks lists any concerns the author raises
about that company (empty if none). Return an entry for every post id given,
with an empty mentions list when no company is mentioned."""

_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "post_id": {"type": "string"},
                    "mentions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "ticker": {"type": "string"},
                                "stance": {"type": "string", "enum": STANCES},
                                "confidence": {"type": "number"},
                                "rationale": {"type": "string"},
                                "risks": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["ticker", "stance", "confidence",
                                         "rationale", "risks"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["post_id", "mentions"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["results"],
    "additionalProperties": False,
}


class ClassifyError(RuntimeError):
    pass


def classify_batch_claude(client, posts, model=DEFAULT_MODEL, known_tickers=()):
    """posts: list of {id, text}. Returns {post_id: [mention dicts]}."""
    payload = [{"post_id": str(p["id"]), "text": p["text"]} for p in posts]
    user = ""
    if known_tickers:
        user += ("Tickers already seen for this author (reuse these spellings): "
                 + ", ".join(sorted(known_tickers)[:300]) + "\n\n")
    user += "Posts:\n" + json.dumps(payload, ensure_ascii=False)

    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "low",
                       "format": {"type": "json_schema", "schema": _SCHEMA}},
    )
    if model.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")):
        # Re-run on Anthropic's recommended fallback model if a safety
        # classifier declines, instead of losing the batch.
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        response = client.beta.messages.create(**kwargs)
    else:
        response = client.messages.create(**kwargs)

    if response.stop_reason == "refusal":
        raise ClassifyError("Claude declined this batch.")
    if response.stop_reason == "max_tokens":
        raise ClassifyError("Batch output was cut off; lower the batch size.")
    text = next(b.text for b in response.content if b.type == "text")
    out = {}
    for r in json.loads(text)["results"]:
        out[r["post_id"]] = [dict(m, method="claude") for m in r["mentions"]]
    return out


# ---------------------------------------------------------------------------
# Rule-based fallback: cashtags plus keyword cues. Much less accurate than
# Claude (misses company names, sarcasm and replies) but free and offline.
# ---------------------------------------------------------------------------
CASHTAG = re.compile(r"\$([A-Za-z][A-Za-z0-9.]{0,9}|\d{3,6})\b")
BULL = re.compile(r"\b(bull|bullish|long|buy|bought|adding|added|accumulat|top pick|"
                  r"favou?rite|upside|undervalued|breakout|loaded|moon|winner|"
                  r"bottleneck|beat)\w*", re.I)
BEAR = re.compile(r"\b(bear|bearish|short|sell|sold|trim|exit|overvalued|downside|"
                  r"avoid|not a fan|dump|squeez|weak|miss|fraud)\w*", re.I)
RISK = re.compile(r"[^.]*\b(risk|concern|headwind|competition|dilution|"
                  r"concentration)\b[^.]*\.?", re.I)


def classify_post_rules(text):
    tickers = []
    for m in CASHTAG.finditer(text):
        t = m.group(1).upper().rstrip(".")
        if t not in tickers:
            tickers.append(t)
    if not tickers:
        return []
    bull, bear = len(BULL.findall(text)), len(BEAR.findall(text))
    risks = [r.group(0).strip() for r in RISK.finditer(text)]
    mentions = []
    for i, t in enumerate(tickers):
        if i > 0 and re.search(r"(also|eye on|vs\.?|like)\s+\$" + re.escape(t), text, re.I):
            stance, conf = "background", 0.5
        elif bull > bear:
            stance, conf = "bullish", 0.55
        elif bear > bull:
            stance, conf = "bearish", 0.55
        else:
            stance, conf = "neutral", 0.4
        mentions.append({"ticker": t, "stance": stance, "confidence": conf,
                         "rationale": "keyword rules", "risks": risks,
                         "method": "rules"})
    return mentions


def classify_posts(posts_df, api_key=None, model=DEFAULT_MODEL,
                   known_tickers=(), on_progress=None):
    """Yields (post_id, mentions) for every row of posts_df.

    Uses Claude in batches when api_key is given; a batch that fails falls
    back to the keyword rules so the run always completes.
    """
    rows = posts_df.to_dict("records")
    client = anthropic.Anthropic(api_key=api_key) if api_key else None
    known = set(known_tickers)
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        result, error = {}, None
        if client:
            try:
                result = classify_batch_claude(client, batch, model, known)
            except (ClassifyError, anthropic.APIError, json.JSONDecodeError,
                    StopIteration, KeyError) as e:
                error = str(e)
        for p in batch:
            pid = str(p["id"])
            ments = result.get(pid)
            if ments is None:
                ments = classify_post_rules(p["text"])
            known.update(m["ticker"].upper() for m in ments)
            yield pid, ments
        if on_progress:
            on_progress(min(start + BATCH_SIZE, len(rows)), len(rows), error)
