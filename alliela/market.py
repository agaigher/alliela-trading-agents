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


def price_pack(ticker):
    """One year of daily bars distilled into the numbers a market
    analyst starts from. Real data or an explicit gap — never invented."""
    try:
        r = httpx.get(CHART.format(ticker),
                      params={"range": "1y", "interval": "1d"},
                      headers=_UA, timeout=20.0, follow_redirects=True)
        r.raise_for_status()
        res = r.json()["chart"]["result"][0]
        meta = res["meta"]
        q = res["indicators"]["quote"][0]
        closes = [c for c in q["close"] if c]
        vols = [v for v in q["volume"] if v]
        if len(closes) < 30:
            return {"ticker": ticker, "status": "insufficient_history"}
        last = closes[-1]

        def ret(days):
            if len(closes) > days:
                return round((last / closes[-days - 1] - 1) * 100, 1)
            return None

        sma = lambda n: (sum(closes[-n:]) / n if len(closes) >= n
                         else None)
        hi, lo = max(closes), min(closes)
        return {
            "ticker": ticker, "status": "ok",
            "currency": meta.get("currency"),
            "price": round(last, 2),
            "returns_pct": {"1m": ret(21), "3m": ret(63),
                            "6m": ret(126), "12m": ret(252)},
            "week52_high": round(hi, 2), "week52_low": round(lo, 2),
            "pct_off_52w_high": round((last / hi - 1) * 100, 1),
            "sma50_rel_pct": (round((last / sma(50) - 1) * 100, 1)
                              if sma(50) else None),
            "sma200_rel_pct": (round((last / sma(200) - 1) * 100, 1)
                               if sma(200) else None),
            "avg_daily_volume_3m": (int(sum(vols[-63:]) / len(vols[-63:]))
                                    if vols else None),
        }
    except Exception:
        return {"ticker": ticker, "status": "data_unavailable"}


def quote_summary(ticker):
    """Fundamentals + positioning modules from Yahoo quoteSummary (the
    crumb-authenticated endpoint), reduced to plain values. Missing
    fields stay missing — coverage gaps are the analyst's to flag."""
    modules = ("financialData,defaultKeyStatistics,summaryDetail,"
               "recommendationTrend,majorHoldersBreakdown")
    try:
        with httpx.Client(headers=_UA, timeout=20.0,
                          follow_redirects=True) as c:
            c.get("https://fc.yahoo.com")
            crumb = c.get("https://query1.finance.yahoo.com"
                          "/v1/test/getcrumb").text
            r = c.get("https://query1.finance.yahoo.com"
                      f"/v10/finance/quoteSummary/{ticker}",
                      params={"modules": modules, "crumb": crumb})
            r.raise_for_status()
            d = r.json()["quoteSummary"]["result"][0]
    except Exception:
        return {"ticker": ticker, "status": "data_unavailable"}

    def v(section, key):
        raw = (d.get(section) or {}).get(key)
        if isinstance(raw, dict):
            return raw.get("fmt") or raw.get("raw")
        return raw

    fund = {k: v("financialData", k) for k in (
        "totalRevenue", "revenueGrowth", "grossMargins",
        "operatingMargins", "profitMargins", "returnOnEquity",
        "totalDebt", "debtToEquity", "freeCashflow",
        "earningsGrowth")}
    fund.update({k: v("defaultKeyStatistics", k) for k in (
        "forwardPE", "trailingEps", "forwardEps", "pegRatio",
        "priceToBook", "enterpriseToEbitda")})
    fund["trailingPE"] = v("summaryDetail", "trailingPE")
    fund["dividendYield"] = v("summaryDetail", "dividendYield")
    fund["marketCap"] = v("summaryDetail", "marketCap")
    positioning = {
        "insidersPercentHeld": v("majorHoldersBreakdown",
                                 "insidersPercentHeld"),
        "institutionsPercentHeld": v("majorHoldersBreakdown",
                                     "institutionsPercentHeld"),
        "shortPercentOfFloat": v("defaultKeyStatistics",
                                 "shortPercentOfFloat"),
        "sharesShort": v("defaultKeyStatistics", "sharesShort"),
        "shortRatio": v("defaultKeyStatistics", "shortRatio"),
        "recommendationTrend": (d.get("recommendationTrend") or
                                {}).get("trend"),
        "targetMeanPrice": v("financialData", "targetMeanPrice"),
        "numberOfAnalystOpinions": v("financialData",
                                     "numberOfAnalystOpinions"),
    }
    return {"ticker": ticker, "status": "ok",
            "fundamentals": {k: x for k, x in fund.items()
                             if x is not None},
            "positioning": {k: x for k, x in positioning.items()
                            if x is not None}}


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
