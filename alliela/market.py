"""Minimal real-market context for the engine — deliberately tiny.

Tier 01 injects fresh headlines as prompt context (a context pack)
rather than running a tool-calling loop; the full discovery-tool loop
arrives with the Selection tier. Google News RSS: keyless, no
dependencies beyond httpx + stdlib."""
import xml.etree.ElementTree as ET

import httpx

RSS = "https://news.google.com/rss/search"


def news_headlines(query, limit=12):
    """[(title, source, published)] for a free-text query."""
    try:
        r = httpx.get(RSS, params={"q": query, "hl": "en-US",
                                   "gl": "US", "ceid": "US:en"},
                      timeout=15.0, follow_redirects=True)
        r.raise_for_status()
        root = ET.fromstring(r.text)
        out = []
        for item in root.iter("item"):
            title = item.findtext("title") or ""
            source = item.findtext("source") or ""
            pub = item.findtext("pubDate") or ""
            out.append((title, source, pub))
            if len(out) >= limit:
                break
        return out
    except Exception:
        return []            # a degraded scan is better than a dead run


def context_pack(queries, per_query=8):
    """Formatted headline block for prompt injection."""
    lines = []
    for q in queries:
        heads = news_headlines(q, per_query)
        if heads:
            lines.append(f"### {q}")
            for title, source, pub in heads:
                lines.append(f"- {title} ({source}, {pub})")
    return "\n".join(lines) if lines else "(no fresh headlines fetched)"
