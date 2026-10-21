"""Per-ticker thesis analysis: latest view, how it evolved, key posts, risks."""

import anthropic

from .classify import DEFAULT_MODEL

QA_SYSTEM = """You summarise one analyst's public posts about a single stock.
Work only from the posts provided; never add outside facts, price targets, or
advice. Cite posts by their [n] number. Write in plain business English with
no em dashes. Use these markdown sections:

### Latest opinion
The most recent explicit stance, its date, and the post [n].

### Thesis narrative
How the argument started and how it changed over time, in 1 to 3 short paragraphs.

### 3 key posts
The three posts that defined the thesis arc, each with [n], date, and one
sentence on why it matters.

### Risks mentioned
Every concern the author raised, with [n]. Say so plainly if none were raised.

### What the posts do not cover
Gaps an investor should check independently (valuation, financials,
competition) that the posts leave open."""

MAX_POSTS = 150


def ticker_brief(ticker, mentions, api_key, model=DEFAULT_MODEL, question=None):
    """mentions: rows for one ticker with created_at, stance, text, url."""
    m = mentions.sort_values("created_at")
    if len(m) > MAX_POSTS:  # keep the start of the arc and the recent posts
        m = m.iloc[list(range(30)) + list(range(len(m) - (MAX_POSTS - 30), len(m)))]
    lines = [f"[{i + 1}] {r.created_at:%Y-%m-%d} ({r.stance}) {r.text}"
             for i, r in enumerate(m.itertuples())]
    prompt = f"Stock: {ticker}\n\nPosts, oldest first:\n" + "\n".join(lines)
    if question:
        prompt += f"\n\nAlso answer this question from the posts: {question}"

    client = anthropic.Anthropic(api_key=api_key)
    kwargs = dict(model=model, max_tokens=16000, system=QA_SYSTEM,
                  messages=[{"role": "user", "content": prompt}],
                  output_config={"effort": "medium"})
    if model.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")):
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        resp = client.beta.messages.create(**kwargs)
    else:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason == "refusal":
        return "Claude declined to summarise these posts.", m
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, m
