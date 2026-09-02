"""Free, keyless tools for the Analyst team (Phase A of the evidence
decision, trading-agents/CLAUDE.md § "Evidence and research volume").

The desk kept passing on every thesis because the numbers it turned on
— segment revenue, filing disclosures, order-book detail — were never
in the context pack. These tools let an analyst go and get them.
Everything here is real and dated: EDGAR for filings and XBRL
financials, GDELT + Google News for dated headlines with links, the
publisher's page for article text, Yahoo for price history, realized
volatility and (US-listed only) implied volatility.

Rules that hold across every tool:
- A tool that cannot answer returns {"status": "unavailable", "why":
  ...} (or a more specific status). Never a fabricated result, never a
  silent empty — the gap is the analyst's to record.
- Results are trimmed to a character budget; the model's context is
  the scarce resource, not the network.
- No keys. EDGAR asks for a User-Agent that identifies the requester;
  it is a contact string, not a credential (EDGAR_USER_AGENT overrides
  the default).
- Coverage is honest: EDGAR covers US filers and foreign private
  issuers (20-F/6-K). A German or Japanese primary listing gets
  article text and price tools; its segment gap stays a gap.
"""
import html as _html
import json
import math
import os
import re
import time
from datetime import date, timedelta

import httpx

from alliela.market import CHART, _UA, news_headlines

EDGAR_UA = {"User-Agent": os.environ.get(
    "EDGAR_USER_AGENT", "Alliela Research hello@alliela.com"),
    "Accept-Encoding": "gzip, deflate"}
GDELT = "https://api.gdeltproject.org/api/v2/doc/doc"
TIMEOUT = 20.0

# Per analyst per pass. A cap the model can see: the refusal it gets
# on the seventh call tells it to write with what it has.
TOOL_BUDGET = 6
RESULT_CHARS = 7000

_cache = {}


def _cached(key, fn):
    if key not in _cache:
        _cache[key] = fn()
    return _cache[key]


def _clip(s, n=RESULT_CHARS):
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n…[trimmed to {n} chars]"


def _text(html_src):
    """HTML → readable text. Stdlib only: scripts/styles dropped, block
    tags become newlines, entities unescaped, whitespace collapsed."""
    # Inline-XBRL filings open with a hidden <ix:header> of raw facts
    # (member names, contexts) that would otherwise be the first
    # "backlog" hit on the page.
    s = re.sub(r"(?is)<ix:header>.*?</ix:header>", " ", html_src)
    s = re.sub(r"(?is)<(script|style|noscript|svg|head)[^>]*>.*?</\1>",
               " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|table|section)>",
               "\n", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = _html.unescape(s)
    s = re.sub(r"[ \t\r\f\v\xa0]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


# ── EDGAR ─────────────────────────────────────────────────────────────

def _cik(ticker):
    """Ticker → 10-digit CIK via EDGAR's own ticker table. Exchange
    suffixes (SIE.DE, 6501.T) are not US tickers and resolve to None."""
    def load():
        r = httpx.get("https://www.sec.gov/files/company_tickers.json",
                      headers=EDGAR_UA, timeout=TIMEOUT)
        r.raise_for_status()
        return {v["ticker"].upper(): (f"{int(v['cik_str']):010d}",
                                      v["title"])
                for v in r.json().values()}
    try:
        table = _cached("edgar_tickers", load)
    except Exception as exc:
        return None, None, f"EDGAR ticker table unavailable: {exc!r}"
    t = ticker.upper().replace("-", ".")
    hit = table.get(t) or table.get(t.replace(".", "-"))
    if not hit:
        return None, None, (f"{ticker} is not in EDGAR's ticker table — "
                            "not a US filer or foreign private issuer")
    return hit[0], hit[1], None


def _submissions(cik):
    def load():
        r = httpx.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                      headers=EDGAR_UA, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    return _cached(f"subs:{cik}", load)


def sec_filings(ticker, forms=None, limit=10):
    cik, name, why = _cik(ticker)
    if not cik:
        return {"status": "unavailable", "why": why}
    try:
        subs = _submissions(cik)
    except Exception as exc:
        return {"status": "unavailable", "why": f"EDGAR: {exc!r}"}
    rec = subs.get("filings", {}).get("recent", {})
    want = {f.upper() for f in (forms or [])}
    out = []
    for form, filed, acc, doc, desc in zip(
            rec.get("form", []), rec.get("filingDate", []),
            rec.get("accessionNumber", []),
            rec.get("primaryDocument", []),
            rec.get("primaryDocDescription", [])):
        if want and form.upper() not in want:
            continue
        acc_nodash = acc.replace("-", "")
        out.append({
            "form": form, "filed": filed, "accession": acc,
            "description": desc,
            "url": (f"https://www.sec.gov/Archives/edgar/data/"
                    f"{int(cik)}/{acc_nodash}/{doc}")})
        if len(out) >= limit:
            break
    return {"status": "ok", "cik": cik, "entity": name,
            "sic": subs.get("sicDescription"),
            "fiscal_year_end": subs.get("fiscalYearEnd"),
            "filings": out}


# The concept an analyst asks for → the tags filers actually use for
# it, across standard changes and taxonomies. Extend as gaps show up.
_ALIASES = {
    "Revenues": ["RevenueFromContractWithCustomerExcludingAssessedTax",
                 "SalesRevenueNet", "Revenue"],
    "Revenue": ["Revenues",
                "RevenueFromContractWithCustomerExcludingAssessedTax"],
    "NetIncome": ["NetIncomeLoss", "ProfitLoss"],
    "NetIncomeLoss": ["ProfitLoss"],
    "OperatingIncome": ["OperatingIncomeLoss"],
    "GrossProfit": ["GrossProfit"],
    "EPS": ["EarningsPerShareDiluted", "EarningsPerShareBasic"],
    "EarningsPerShare": ["EarningsPerShareDiluted",
                         "EarningsPerShareBasic"],
    "OperatingCashFlow": ["NetCashProvidedByUsedInOperatingActivities"],
    "Capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "CapitalExpenditures": [
        "PaymentsToAcquirePropertyPlantAndEquipment"],
    "Debt": ["LongTermDebt", "LongTermDebtNoncurrent",
             "DebtInstrumentCarryingAmount"],
    "LongTermDebt": ["LongTermDebtNoncurrent",
                     "LongTermDebtAndCapitalLeaseObligations"],
    "Cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCash"
             "Equivalents"],
    "Backlog": ["RevenueRemainingPerformanceObligation"],
    "RemainingPerformanceObligation": [
        "RevenueRemainingPerformanceObligation"],
    "Inventory": ["InventoryNet"],
    "Equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableTo"
               "NoncontrollingInterest"],
    "SharesOutstanding": ["CommonStockSharesOutstanding",
                          "EntityCommonStockSharesOutstanding"],
    "RnD": ["ResearchAndDevelopmentExpense"],
    "ResearchAndDevelopment": ["ResearchAndDevelopmentExpense"],
}


def _companyfacts(cik):
    def load():
        r = httpx.get(
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=EDGAR_UA, timeout=40.0)
        r.raise_for_status()
        return r.json()
    return _cached(f"facts:{cik}", load)


def sec_financials(ticker, concepts, periods=8):
    """As-reported XBRL values per concept, newest first, with the
    period end, fiscal year/period and the filing they came from.

    companyfacts carries consolidated (non-dimensional) facts only —
    segment splits are in the filing's segment note, which is what
    sec_filing_section is for. Said here so the analyst does not read
    an absent segment as a zero."""
    cik, name, why = _cik(ticker)
    if not cik:
        return {"status": "unavailable", "why": why}
    try:
        facts = _companyfacts(cik)
    except Exception as exc:
        return {"status": "unavailable", "why": f"EDGAR: {exc!r}"}
    taxonomies = facts.get("facts", {})
    available = sorted(set(
        k for tax in taxonomies.values() for k in tax))

    def series(concept):
        for tax_name, tax in taxonomies.items():
            if concept in tax:
                node = tax[concept]
                rows = []
                for unit, vals in node.get("units", {}).items():
                    for v in vals:
                        rows.append({"end": v.get("end"),
                                     "start": v.get("start"),
                                     "val": v.get("val"), "unit": unit,
                                     "fy": v.get("fy"), "fp": v.get("fp"),
                                     "form": v.get("form"),
                                     "filed": v.get("filed")})
                # Newest period end first; among duplicates (the same
                # period restated in later filings) keep the most
                # recently filed.
                rows.sort(key=lambda r: (r["end"] or "",
                                         r["filed"] or ""), reverse=True)
                return tax_name, node.get("label"), rows
        return None

    result, missing = {}, []
    for concept in concepts[:12]:
        # Filers retag as standards change (Revenues became
        # RevenueFromContractWithCustomer… under ASC 606), so a concept
        # can be real and years stale at once. Try its aliases and keep
        # whichever is most recently reported.
        candidates = [concept] + [a for a in _ALIASES.get(concept, [])
                                  if a != concept]
        best = None
        for cand in candidates:
            got = series(cand)
            if got and got[2]:
                if best is None or (got[2][0]["end"] or "") > \
                        (best[3][0]["end"] or ""):
                    best = (cand, got[0], got[1], got[2])
        if not best:
            missing.append(concept)
            continue
        used, tax_name, label, rows = best
        seen, kept = set(), []
        for r in rows:
            k = (r["end"], r["start"], r["fp"])
            if k in seen:
                continue
            seen.add(k)
            kept.append(r)
            if len(kept) >= periods:
                break
        entry = {"taxonomy": tax_name, "label": label, "values": kept}
        if used != concept:
            entry["reported_as"] = used
        newest = kept[0]["end"] or ""
        if newest < (date.today() - timedelta(days=550)).isoformat():
            entry["stale"] = (f"newest value ends {newest} — the filer "
                              "no longer tags this concept; see "
                              "'nearest' for what it uses now")
            stem = re.sub(r"[^A-Za-z]", "", concept)[:7].lower()
            entry["nearest"] = [a for a in available
                                if stem and stem in a.lower()][:8]
        result[concept] = entry
    hint = []
    if missing:
        # Offer the nearest concept names so the second call lands.
        for m in missing:
            stem = re.sub(r"[^A-Za-z]", "", m)[:6].lower()
            near = [a for a in available if stem and stem in a.lower()]
            hint.append({"asked": m, "nearest": near[:8]})
    return {"status": "ok", "cik": cik, "entity": name,
            "note": ("consolidated facts only — segment splits live in "
                     "the filing's segment note (sec_filing_section)"),
            "concepts": result, "missing": hint}


_SECTION_PATTERNS = {
    # 10-K
    "business": r"item\s*1\.?\s*business",
    "risk_factors": r"item\s*1a\.?\s*risk\s*factors",
    # Filers write MANAGEMENT’S with a curly apostrophe; .{0,3} takes
    # either quote, or none.
    "mdna": r"item\s*7\.?\s*management.{0,3}s\s*discussion",
    "financial_statements": r"item\s*8\.?\s*financial\s*statements",
    # 10-Q (MD&A is Item 2 there)
    "mdna_10q": r"item\s*2\.?\s*management.{0,3}s\s*discussion",
    # notes, any form
    "segment": r"(segment\s+information|segment\s+reporting|"
               r"reportable\s+segments|business\s+segments)",
    "guidance": r"(outlook|guidance|expect(?:s|ed)?\s+(?:to|that)|"
                r"forward[- ]looking)",
    "backlog": r"(backlog|remaining\s+performance\s+obligations|"
               r"order\s+(?:book|intake))",
    "liquidity": r"liquidity\s+and\s+capital\s+resources",
}


def sec_filing_section(ticker, section, form=None, accession=None,
                       max_chars=6000):
    """One section of a filing as text: a named 10-K/10-Q item, or a
    keyword-located passage (segment note, backlog, guidance).

    Locating an item in filer-formatted HTML is heuristic. When the
    heading is not found the tool says so and returns the passages
    around the best keyword hit instead — labelled, so the analyst
    knows it is reading a search result, not the item."""
    cik, name, why = _cik(ticker)
    if not cik:
        return {"status": "unavailable", "why": why}
    forms = [form] if form else ["10-K", "10-Q", "20-F"]
    listing = sec_filings(ticker, forms=forms, limit=40)
    if listing.get("status") != "ok" or not listing["filings"]:
        return {"status": "unavailable",
                "why": f"no {forms} filings on EDGAR for {ticker}"}
    filing = None
    if accession:
        filing = next((f for f in listing["filings"]
                       if f["accession"] == accession), None)
        if not filing:
            return {"status": "unavailable",
                    "why": f"accession {accession} not among recent "
                           f"{forms} filings"}
    else:
        filing = listing["filings"][0]
    try:
        r = httpx.get(filing["url"], headers=EDGAR_UA, timeout=40.0,
                      follow_redirects=True)
        r.raise_for_status()
        text = _text(r.text)
    except Exception as exc:
        return {"status": "unavailable", "why": f"fetch: {exc!r}",
                "filing": filing}
    key = section.strip().lower().replace(" ", "_").replace("&", "n")
    if key in ("md&a", "mdanda", "mda"):
        key = "mdna"
    if key == "mdna" and filing["form"].upper().startswith("10-Q"):
        key = "mdna_10q"
    pattern = _SECTION_PATTERNS.get(key) or re.escape(section)
    hits = [m.start() for m in re.finditer(pattern, text, re.I)]
    base = {"status": "ok", "filing": filing, "section": section,
            "text_chars": len(text)}
    located = None
    if not hits and key not in _SECTION_PATTERNS:
        # A free phrase ("Electrical Americas operating margin") rarely
        # appears verbatim. Fall back to passages where most of its
        # significant words co-occur — labelled as approximate.
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", section)
                 if w.lower() not in ("with", "from", "that", "this",
                                      "and", "the", "for")]
        if len(words) >= 2:
            scored = []
            for m in re.finditer(re.escape(words[0]), text, re.I):
                win = text[m.start(): m.start() + 1500].lower()
                n = sum(1 for w in words[1:] if w.lower() in win)
                if n >= max(1, (len(words) - 1) // 2):
                    scored.append((n, m.start()))
            scored.sort(reverse=True)
            hits = [h for _, h in scored[:6]]
            if hits:
                located = (f"approximate — passages with most of: "
                           f"{' '.join(words)}")
    if not hits:
        return {**base, "status": "section_not_located",
                "why": f"'{section}' not found in {filing['form']} "
                       f"{filing['filed']}; the filing is "
                       f"{len(text)} chars",
                "opening": text[:min(max_chars, 2000)]}
    # The table of contents matches first for named items; the real
    # heading is the later, longer-bodied match. Take the hit with the
    # most text before the next item heading.
    if key in _SECTION_PATTERNS and key not in ("segment", "guidance",
                                                 "backlog"):
        best = max(hits, key=lambda h: len(
            re.split(r"(?i)\bitem\s+\d+[a-c]?\.", text[h + 20:], 1)[0]))
        body = text[best:best + max_chars]
        return {**base, "located": "item heading", "text": body}
    # Keyword sections: concatenate windows around the strongest hits.
    windows, used = [], 0
    for h in hits[:6]:
        w = text[max(0, h - 300): h + 1500]
        windows.append(w)
        used += len(w)
        if used >= max_chars:
            break
    return {**base, "located": located or f"keyword — {len(hits)} hit(s)",
            "text": _clip("\n…\n".join(windows), max_chars)}


# EDGAR full-text search (efts.sec.gov) answers 403 to every
# non-browser client as of Sep 2026, whatever the headers. Not offered:
# a tool that always fails teaches the analyst to stop calling tools.

# ── News and article text ─────────────────────────────────────────────

def news_search(query, days=90, limit=15):
    """Dated news for a query, from three keyless sources: Yahoo
    Finance's news search (publisher links — the ones article_text can
    fetch), GDELT when reachable (global, best-effort — it times out
    from some networks), and Google News titles for breadth."""
    out = {"status": "ok", "query": query, "articles": [],
           "headlines": []}
    seen_urls = set()
    try:
        r = httpx.get("https://query1.finance.yahoo.com/v1/finance/search",
                      params={"q": query, "newsCount": min(int(limit), 20),
                              "quotesCount": 0},
                      headers=_UA, timeout=TIMEOUT)
        r.raise_for_status()
        for n in (r.json().get("news") or []):
            url = n.get("link")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            ts = n.get("providerPublishTime")
            out["articles"].append({
                "title": n.get("title"), "url": url,
                "source": n.get("publisher"),
                "date": (date.fromtimestamp(ts).isoformat()
                         if ts else None),
                "tickers": n.get("relatedTickers")})
    except Exception as exc:
        out["yahoo"] = f"unavailable: {exc!r}"
    # GDELT is unreachable from some networks and times out slowly;
    # after one failure in a process it is skipped, not retried on
    # every call — 8 s per analyst per query adds up.
    if _cache.get("gdelt_down"):
        out["gdelt"] = "skipped: unreachable earlier this run"
    else:
        try:
            span = min(max(int(days), 1), 365)
            r = httpx.get(GDELT, params={
                "query": query, "mode": "artlist", "format": "json",
                "maxrecords": min(int(limit), 50), "sort": "datedesc",
                "timespan": f"{span}d"}, timeout=8.0)
            r.raise_for_status()
            for a in (r.json().get("articles") or []):
                url = a.get("url")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                seen = a.get("seendate", "")
                out["articles"].append({
                    "title": a.get("title"), "url": url,
                    "source": a.get("domain"),
                    "date": (f"{seen[:4]}-{seen[4:6]}-{seen[6:8]}"
                             if len(seen) >= 8 else seen),
                    "language": a.get("language")})
        except Exception as exc:
            _cache["gdelt_down"] = True
            out["gdelt"] = f"unavailable: {type(exc).__name__}"
    for title, source, pub in news_headlines(query, limit):
        out["headlines"].append({"title": title, "source": source,
                                 "published": pub})
    if not out["articles"] and not out["headlines"]:
        return {"status": "unavailable", "query": query,
                "why": "no news source returned anything"}
    return out


def article_text(url, max_chars=5000):
    """The body of a news article or IR page. Paywalls and bot walls
    are reported as such — a 403 is a fact, not a gap to paper over.
    Google News redirect links cannot be resolved without a browser;
    use the publisher URL that news_search returns."""
    if "news.google.com" in url:
        return {"status": "unavailable", "url": url,
                "why": "Google News redirect links resolve only in a "
                       "browser — use the publisher URL from "
                       "news_search's 'articles'"}
    if "sec.gov/cgi-bin/viewer" in url or "sec.gov/ix?doc=" in url:
        return {"status": "unavailable", "url": url,
                "why": "EDGAR's viewer is a JavaScript shell — fetch "
                       "the primary document URL that sec_filings "
                       "returns (…/Archives/edgar/data/…), or use "
                       "sec_filing_section"}
    try:
        r = httpx.get(url, headers={**_UA, "Accept": "text/html,*/*"},
                      timeout=TIMEOUT, follow_redirects=True)
    except Exception as exc:
        return {"status": "unavailable", "url": url, "why": repr(exc)}
    if r.status_code in (401, 402, 403, 451):
        return {"status": "blocked", "url": url,
                "why": f"HTTP {r.status_code} — paywall or bot wall"}
    if r.status_code >= 400:
        return {"status": "unavailable", "url": url,
                "why": f"HTTP {r.status_code}"}
    src = r.text
    title = re.search(r"(?is)<title[^>]*>(.*?)</title>", src)
    title = _html.unescape(title.group(1)).strip() if title else ""
    # Consent and bot walls answer 200 with a page that is not the
    # article. Naming them is the difference between "blocked" and a
    # cookie-policy paragraph cited as evidence.
    final = str(r.url)
    walls = ("guce.yahoo.com", "consent.yahoo.com", "consent.google",
             "/captcha", "challenge-platform")
    wall_titles = ("your privacy choices", "just a moment",
                   "access denied", "attention required",
                   "are you a robot", "consent")
    if any(w in final for w in walls) or \
            any(t in title.lower() for t in wall_titles):
        return {"status": "blocked", "url": url, "final_url": final,
                "why": f"consent or bot wall: '{title[:60]}'"}
    # Prefer <article>/<main>; fall back to the whole page.
    m = re.search(r"(?is)<article[^>]*>(.*?)</article>", src) \
        or re.search(r"(?is)<main[^>]*>(.*?)</main>", src)
    body = _text(m.group(1) if m else src)
    if len(body) < 400:
        return {"status": "thin", "url": url, "title": title,
                "why": "page rendered client-side or is mostly "
                       "navigation; only "
                       f"{len(body)} chars of text found",
                "text": body}
    return {"status": "ok", "url": final, "title": title,
            "text": _clip(body, max_chars)}


# ── Prices, volatility, options ───────────────────────────────────────

def _bars(ticker, rng, interval="1d"):
    r = httpx.get(CHART.format(ticker),
                  params={"range": rng, "interval": interval},
                  headers=_UA, timeout=TIMEOUT, follow_redirects=True)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    bars = [(date.fromtimestamp(t).isoformat(), c, v)
            for t, c, v in zip(res["timestamp"], q["close"],
                               q["volume"]) if c]
    return res.get("meta") or {}, bars


def price_history(ticker, range="1y", interval="1wk", max_points=120):
    """Dated closes at a coarse interval — enough to see the path, few
    enough to fit in a prompt."""
    if range not in ("3mo", "6mo", "1y", "2y", "5y", "10y"):
        return {"status": "unavailable",
                "why": "range must be one of 3mo 6mo 1y 2y 5y 10y"}
    if interval not in ("1d", "1wk", "1mo"):
        return {"status": "unavailable",
                "why": "interval must be 1d, 1wk or 1mo"}
    try:
        got = _bars(ticker, range, interval)
    except Exception as exc:
        return {"status": "unavailable", "why": repr(exc)}
    if not got:
        return {"status": "not_found", "ticker": ticker}
    meta, bars = got
    if len(bars) > max_points:
        step = math.ceil(len(bars) / max_points)
        bars = bars[::step] + ([bars[-1]] if bars[-1] not in bars[::step]
                               else [])
    return {"status": "ok", "ticker": ticker,
            "currency": meta.get("currency"),
            "exchange": meta.get("fullExchangeName"),
            "interval": interval, "points": len(bars),
            "bars": [[d, round(c, 2), v] for d, c, v in bars]}


def realized_vol(ticker, windows=(20, 60, 120, 252)):
    """Annualised realized volatility from daily log returns, per
    window — the Risk panel's missing input."""
    try:
        got = _bars(ticker, "2y", "1d")
    except Exception as exc:
        return {"status": "unavailable", "why": repr(exc)}
    if not got:
        return {"status": "not_found", "ticker": ticker}
    _, bars = got
    closes = [c for _, c, _ in bars]
    rets = [math.log(b / a) for a, b in zip(closes, closes[1:])
            if a and b]
    out = {}
    for w in windows:
        w = int(w)
        if len(rets) < w + 1:
            out[f"{w}d"] = None
            continue
        seg = rets[-w:]
        mu = sum(seg) / w
        var = sum((x - mu) ** 2 for x in seg) / (w - 1)
        out[f"{w}d"] = round(math.sqrt(var) * math.sqrt(252) * 100, 1)
    hi, lo = max(closes[-252:]), min(closes[-252:])
    return {"status": "ok", "ticker": ticker, "as_of": bars[-1][0],
            "realized_vol_pct_annualised": out,
            "max_drawdown_1y_pct": round((lo / hi - 1) * 100, 1),
            "sessions": len(closes)}


def options_iv(ticker):
    """ATM implied volatility from the nearest listed expiries and the
    put/call open-interest balance. Yahoo lists options for US-listed
    names; anything else comes back honestly empty."""
    try:
        with httpx.Client(headers=_UA, timeout=TIMEOUT,
                          follow_redirects=True) as c:
            c.get("https://fc.yahoo.com")
            crumb = c.get("https://query1.finance.yahoo.com"
                          "/v1/test/getcrumb").text
            r = c.get("https://query1.finance.yahoo.com"
                      f"/v7/finance/options/{ticker}",
                      params={"crumb": crumb})
            r.raise_for_status()
            res = r.json()["optionChain"]["result"]
    except Exception as exc:
        return {"status": "unavailable", "why": repr(exc)}
    if not res or not res[0].get("options"):
        return {"status": "no_listed_options", "ticker": ticker,
                "why": "no option chain on Yahoo — typically a non-US "
                       "listing"}
    chain = res[0]
    spot = (chain.get("quote") or {}).get("regularMarketPrice")
    expiries = []
    for ex in chain["options"][:2]:
        calls, puts = ex.get("calls") or [], ex.get("puts") or []

        def atm(rows):
            rows = [x for x in rows if x.get("impliedVolatility")]
            if not rows or not spot:
                return None
            best = min(rows, key=lambda x: abs(x["strike"] - spot))
            return {"strike": best["strike"],
                    "iv_pct": round(best["impliedVolatility"] * 100, 1),
                    "open_interest": best.get("openInterest")}
        expiries.append({
            "expiry": date.fromtimestamp(ex["expirationDate"]).isoformat(),
            "atm_call": atm(calls), "atm_put": atm(puts),
            "put_call_oi_ratio": (
                round(sum(p.get("openInterest") or 0 for p in puts)
                      / max(1, sum(c.get("openInterest") or 0
                                   for c in calls)), 2))})
    return {"status": "ok", "ticker": ticker, "spot": spot,
            "expiries": expiries}


# ── Registry ──────────────────────────────────────────────────────────

def _spec(name, description, properties, required):
    return {"type": "function",
            "function": {"name": name, "description": description,
                         "parameters": {"type": "object",
                                        "properties": properties,
                                        "required": required}}}


SPECS = {
    "sec_filings": _spec(
        "sec_filings",
        "List a company's recent SEC filings (form, date, accession, "
        "URL). US filers and foreign private issuers (20-F/6-K) only.",
        {"ticker": {"type": "string"},
         "forms": {"type": "array", "items": {"type": "string"},
                   "description": "e.g. ['10-K','10-Q','8-K']"},
         "limit": {"type": "integer", "default": 10}},
        ["ticker"]),
    "sec_financials": _spec(
        "sec_financials",
        "As-reported XBRL values for named us-gaap/ifrs concepts (e.g. "
        "Revenues, OperatingIncomeLoss, NetIncomeLoss, "
        "LongTermDebt, NetCashProvidedByUsedInOperatingActivities), "
        "newest periods first, with the filing each came from. "
        "Consolidated only — segment splits are in the filing's segment "
        "note (use sec_filing_section).",
        {"ticker": {"type": "string"},
         "concepts": {"type": "array", "items": {"type": "string"}},
         "periods": {"type": "integer", "default": 8}},
        ["ticker", "concepts"]),
    "sec_filing_section": _spec(
        "sec_filing_section",
        "Text of one section of the latest 10-K/10-Q/20-F: a named item "
        "(business, risk_factors, mdna, liquidity) or a keyword-located "
        "passage (segment, backlog, guidance, or any phrase).",
        {"ticker": {"type": "string"},
         "section": {"type": "string"},
         "form": {"type": "string",
                  "description": "10-K, 10-Q or 20-F; default latest "
                                 "of any"},
         "accession": {"type": "string"},
         "max_chars": {"type": "integer", "default": 6000}},
        ["ticker", "section"]),
    "news_search": _spec(
        "news_search",
        "Dated news for a free-text query: articles with publisher URLs "
        "(fetchable with article_text) plus headline titles.",
        {"query": {"type": "string"},
         "days": {"type": "integer", "default": 90},
         "limit": {"type": "integer", "default": 15}},
        ["query"]),
    "article_text": _spec(
        "article_text",
        "The text of a news article or company IR page at a publisher "
        "URL. Paywalls are reported as 'blocked'.",
        {"url": {"type": "string"},
         "max_chars": {"type": "integer", "default": 5000}},
        ["url"]),
    "price_history": _spec(
        "price_history",
        "Dated closes and volume for a ticker at a coarse interval.",
        {"ticker": {"type": "string"},
         "range": {"type": "string", "default": "1y",
                   "description": "3mo 6mo 1y 2y 5y 10y"},
         "interval": {"type": "string", "default": "1wk",
                      "description": "1d 1wk 1mo"}},
        ["ticker"]),
    "realized_vol": _spec(
        "realized_vol",
        "Annualised realized volatility over 20/60/120/252 sessions and "
        "the 1-year max drawdown.",
        {"ticker": {"type": "string"}},
        ["ticker"]),
    "options_iv": _spec(
        "options_iv",
        "ATM implied volatility for the two nearest expiries and the "
        "put/call open-interest ratio. US-listed names only.",
        {"ticker": {"type": "string"}},
        ["ticker"]),
}

IMPL = {
    "sec_filings": sec_filings,
    "sec_financials": sec_financials,
    "sec_filing_section": sec_filing_section,
    "news_search": news_search,
    "article_text": article_text,
    "price_history": price_history,
    "realized_vol": realized_vol,
    "options_iv": options_iv,
}

# Which analyst may call what. A lens is a lens: the Market Analyst
# does not read 10-Ks and the Fundamentals Analyst does not chase
# headlines — the Lead's audit is where those cross.
TOOLSETS = {
    "market": ["price_history", "realized_vol", "options_iv",
               "news_search"],
    "sentiment": ["options_iv", "sec_filings", "news_search",
                  "article_text"],
    "news": ["news_search", "article_text", "sec_filings",
             "sec_filing_section"],
    "fundamentals": ["sec_financials", "sec_filing_section",
                     "sec_filings", "price_history"],
}


def specs_for(names):
    return [SPECS[n] for n in names if n in SPECS]


def execute(name, args):
    """Run one tool. Every failure mode is a status, never an
    exception — a tool that raises would take the paid run with it."""
    fn = IMPL.get(name)
    if fn is None:
        return ({"status": "unavailable",
                 "why": f"no tool named {name}"}, 0)
    started = time.monotonic()
    try:
        result = fn(**(args or {}))
    except TypeError as exc:
        result = {"status": "unavailable",
                  "why": f"bad arguments for {name}: {exc}"}
    except Exception as exc:
        result = {"status": "unavailable", "why": repr(exc)}
    ms = int((time.monotonic() - started) * 1000)
    # Character budget on the serialised result, whatever its shape.
    text = json.dumps(result, ensure_ascii=False, default=str)
    if len(text) > RESULT_CHARS * 2:
        result = {"status": result.get("status", "ok")
                  if isinstance(result, dict) else "ok",
                  "trimmed": True,
                  "text": _clip(text, RESULT_CHARS * 2)}
    return result, ms
