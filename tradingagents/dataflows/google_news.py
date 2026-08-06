"""Google News RSS search (Alliela addition).

Free, keyless, free-text news search — the fallback vendor for
``search_news`` when yfinance's Search endpoint returns nothing useful
for thematic queries like "environment in Japan". Uses only stdlib XML
parsing plus ``requests`` (already a yfinance dependency).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Optional

import requests
from dateutil.relativedelta import relativedelta

from .config import get_config

_RSS_URL = "https://news.google.com/rss/search"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )
}


def search_news_google(
    query: str,
    curr_date: Optional[str] = None,
    look_back_days: Optional[int] = None,
    limit: Optional[int] = None,
) -> str:
    """Search Google News for ``query`` and return formatted headlines.

    Args:
        query: Free-text search query (theme, sector, geography, event).
        curr_date: Anchor date in yyyy-mm-dd; articles published after it
            are dropped (look-ahead guard). ``None`` means today.
        look_back_days: Search window. ``None`` falls back to
            ``global_news_lookback_days`` from the active config.
        limit: Max articles. ``None`` falls back to
            ``global_news_article_limit`` from the active config.

    Returns:
        Formatted string of headlines (title, source, date, link).
    """
    config = get_config()
    if look_back_days is None:
        look_back_days = config["global_news_lookback_days"]
    if limit is None:
        limit = config["global_news_article_limit"]

    try:
        response = requests.get(
            _RSS_URL,
            params={
                "q": f"{query} when:{look_back_days}d",
                "hl": "en-US",
                "gl": "US",
                "ceid": "US:en",
            },
            headers=_HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception as e:  # network / parse errors become tool output
        return f"Error searching Google News for '{query}': {e}"

    curr_dt = None
    if curr_date:
        try:
            curr_dt = datetime.strptime(curr_date, "%Y-%m-%d")
        except ValueError:
            pass

    items = root.findall(".//item")
    news_str = ""
    count = 0
    for item in items:
        if count >= limit:
            break
        title = (item.findtext("title") or "No title").strip()
        link = (item.findtext("link") or "").strip()
        source = (item.findtext("source") or "Unknown").strip()
        pub_raw = item.findtext("pubDate") or ""

        pub_dt = None
        if pub_raw:
            try:
                pub_dt = parsedate_to_datetime(pub_raw).replace(tzinfo=None)
            except (ValueError, TypeError):
                pass

        # Look-ahead guard: drop articles published after the anchor date.
        if curr_dt and pub_dt and pub_dt > curr_dt + relativedelta(days=1):
            continue

        news_str += f"### {title} (source: {source})\n"
        if pub_dt:
            news_str += f"Date: {pub_dt.strftime('%Y-%m-%d')}\n"
        if link:
            news_str += f"Link: {link}\n"
        news_str += "\n"
        count += 1

    if count == 0:
        return f"No news found for query '{query}' in the past {look_back_days} days"

    return f"## News search results for '{query}' (past {look_back_days} days):\n\n{news_str}"
