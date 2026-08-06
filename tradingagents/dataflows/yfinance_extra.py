"""yfinance-backed discovery tools (Alliela additions).

Tools the Idea Generation desks need before a ticker is known or
committed to: free-text news search, a tradability snapshot for
candidate validation, and an earnings calendar for dated catalysts.
Kept out of the vendored y_finance.py / yfinance_news.py so upstream
``git subtree pull`` merges stay clean.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import yfinance as yf
from dateutil.relativedelta import relativedelta

from .config import get_config
from .stockstats_utils import yf_retry
from .yfinance_news import _extract_article_data


def search_news_yfinance(
    query: str,
    curr_date: Optional[str] = None,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Free-text news search via yfinance's Search endpoint.

    Same shape as ``get_global_news_yfinance`` but for a single ad-hoc
    query instead of the configured macro query list, so the Idea
    Generation desks can chase a mandate ("environment in Japan",
    "Nordic industrials") rather than a ticker.
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    try:
        search = yf_retry(lambda: yf.Search(
            query=query,
            news_count=limit,
            enable_fuzzy_query=True,
        ))
        articles = search.news or []
    except Exception as e:
        return f"Error searching news for '{query}': {e}"

    curr_dt = None
    if curr_date:
        try:
            curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        except ValueError:
            pass

    news_str = ""
    count = 0
    seen_titles = set()
    for article in articles:
        if count >= limit:
            break
        if "content" in article:
            data = _extract_article_data(article)
            # Look-ahead guard: drop articles published after the anchor date.
            if curr_dt and data.get("pub_date"):
                pub_naive = data["pub_date"].replace(tzinfo=None)
                if pub_naive > curr_dt + relativedelta(days=1):
                    continue
            title, publisher = data["title"], data["publisher"]
            link, summary = data["link"], data["summary"]
        else:
            title = article.get("title", "No title")
            publisher = article.get("publisher", "Unknown")
            link = article.get("link", "")
            summary = ""

        if not title or title in seen_titles:
            continue
        seen_titles.add(title)

        news_str += f"### {title} (source: {publisher})\n"
        if summary:
            news_str += f"{summary}\n"
        if link:
            news_str += f"Link: {link}\n"
        news_str += "\n"
        count += 1

    if count == 0:
        return f"No news found for query '{query}'"

    return f"## News search results for '{query}':\n\n{news_str}"


def get_ticker_snapshot_yfinance(ticker: str) -> str:
    """Tradability snapshot for a candidate instrument.

    Validates that the ticker resolves and reports the facts an idea desk
    or the Head of Idea Generation needs for the liquidity / coverage
    screen: name, exchange, currency, price, market cap, average daily
    volume and value traded, sector, and 52-week range.
    """
    try:
        t = yf.Ticker(ticker)
        info = yf_retry(lambda: t.get_info()) or {}
    except Exception as e:
        return f"Could not resolve ticker '{ticker}': {e}"

    price = info.get("regularMarketPrice") or info.get("currentPrice")
    if price is None:
        return (
            f"Ticker '{ticker}' did not resolve to a priced instrument — "
            "treat it as unverified and do not put it in an ideas book."
        )

    currency = info.get("currency", "?")
    avg_volume = info.get("averageVolume")
    adv_value = avg_volume * price if avg_volume else None

    def _fmt(value, pattern="{:,.0f}"):
        return pattern.format(value) if value is not None else "n/a"

    lines = [
        f"## Snapshot: {info.get('longName') or info.get('shortName') or ticker} ({ticker})",
        "",
        f"- Exchange: {info.get('fullExchangeName') or info.get('exchange', 'n/a')}",
        f"- Quote type: {info.get('quoteType', 'n/a')}",
        f"- Currency: {currency}",
        f"- Last price: {_fmt(price, '{:,.2f}')} {currency}",
        f"- Market cap: {_fmt(info.get('marketCap'))} {currency}",
        f"- Average daily volume: {_fmt(avg_volume)} shares",
        f"- Average daily value traded: {_fmt(adv_value)} {currency}",
        f"- 52-week range: {_fmt(info.get('fiftyTwoWeekLow'), '{:,.2f}')}"
        f" – {_fmt(info.get('fiftyTwoWeekHigh'), '{:,.2f}')} {currency}",
        f"- Sector / industry: {info.get('sector', 'n/a')} / {info.get('industry', 'n/a')}",
        f"- Country: {info.get('country', 'n/a')}",
    ]
    return "\n".join(lines)


def get_earnings_calendar_yfinance(
    ticker: str,
    curr_date: Optional[str] = None,
) -> str:
    """Upcoming and recent earnings dates for a candidate instrument.

    The Catalyst desk's primary source of dated, verifiable events.
    ``curr_date`` (yyyy-mm-dd) splits upcoming from past; ``None`` means
    today.
    """
    try:
        t = yf.Ticker(ticker)
        earnings = yf_retry(lambda: t.get_earnings_dates(limit=12))
    except Exception as e:
        return f"Error fetching earnings calendar for '{ticker}': {e}"

    if earnings is None or earnings.empty:
        return f"No earnings calendar data available for '{ticker}'"

    try:
        anchor = (
            datetime.strptime(curr_date, "%Y-%m-%d")
            if curr_date
            else datetime.now()
        )
    except ValueError:
        anchor = datetime.now()

    upcoming, past = [], []
    for date, row in earnings.iterrows():
        entry_date = date.to_pydatetime().replace(tzinfo=None)
        estimate = row.get("EPS Estimate")
        reported = row.get("Reported EPS")
        parts = [entry_date.strftime("%Y-%m-%d")]
        if estimate == estimate and estimate is not None:  # NaN-safe
            parts.append(f"EPS estimate {estimate:.2f}")
        if reported == reported and reported is not None:
            parts.append(f"reported {reported:.2f}")
        line = " · ".join(parts)
        (upcoming if entry_date >= anchor else past).append(line)

    lines = [f"## Earnings calendar: {ticker}", ""]
    lines.append("### Upcoming")
    if upcoming:
        lines += [f"- {entry}" for entry in sorted(upcoming)]
    else:
        lines.append("- No dated upcoming earnings found — treat any "
                     "earnings-based catalyst for this name as undated.")
    lines.append("")
    lines.append("### Recent")
    lines += [f"- {entry}" for entry in sorted(past, reverse=True)[:6]] or ["- none"]
    return "\n".join(lines)
