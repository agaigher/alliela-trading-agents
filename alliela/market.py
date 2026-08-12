"""Minimal real-market data for the engine — deliberately tiny.

Deterministic pre-fetch injected as prompt context (a context pack),
not a tool-calling loop. Google News RSS for headlines (Tier 01),
Yahoo Finance chart API for ticker verification + liquidity (Tier 02's
feasibility gate). Keyless, httpx + stdlib only."""
import xml.etree.ElementTree as ET

import httpx

RSS = "https://news.google.com/rss/search"
CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{}"
_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
_FX = {}


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


def _chart(symbol):
    r = httpx.get(CHART.format(symbol),
                  params={"range": "1mo", "interval": "1d"},
                  headers=_UA, timeout=15.0, follow_redirects=True)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()["chart"]["result"][0]


def _fx_to_usd(currency):
    """Rough spot rate for ADV conversion; cached per process.
    'GBp' (London pence) converts via GBP / 100."""
    if not currency or currency == "USD":
        return 1.0
    if currency in _FX:
        return _FX[currency]
    base = "GBP" if currency == "GBp" else currency.upper()
    try:
        res = _chart(f"{base}USD=X")
        rate = float(res["meta"]["regularMarketPrice"])
        if currency == "GBp":
            rate /= 100.0
    except Exception:
        rate = None
    _FX[currency] = rate
    return rate


def ticker_snapshot(ticker):
    """Verify a candidate resolves and report the liquidity screen.
    status: 'ok' | 'not_found' (fantasy name — fatal downstream) |
    'data_unavailable' (transient — score conservatively, never fatal).
    Real data: the feasibility gate runs on this, not on model claims."""
    try:
        res = _chart(ticker)
    except Exception:
        return {"ticker": ticker, "status": "data_unavailable"}
    if not res:
        return {"ticker": ticker, "status": "not_found"}
    meta = res.get("meta") or {}
    adv_usd = None
    try:
        q = res["indicators"]["quote"][0]
        pairs = [(c, v) for c, v in zip(q["close"], q["volume"])
                 if c and v]
        if pairs:
            adv_local = sum(c * v for c, v in pairs) / len(pairs)
            fx = _fx_to_usd(meta.get("currency"))
            if fx:
                adv_usd = int(adv_local * fx)
    except Exception:
        pass
    return {
        "ticker": ticker,
        "status": "ok",
        "name": meta.get("longName") or meta.get("shortName") or "",
        "exchange": meta.get("fullExchangeName")
        or meta.get("exchangeName") or "",
        "currency": meta.get("currency") or "",
        "price": meta.get("regularMarketPrice"),
        "adv_value_usd": adv_usd,
    }


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
