"""Discovery tools for the Idea Generation desks (Alliela addition).

These run before a ticker is committed to: free-text news search for
working a mandate, a tradability snapshot for validating candidates,
and an earnings calendar for dated catalysts. All route through the
vendor layer like every other tool.
"""

from typing import Annotated, Optional

from langchain_core.tools import tool

from tradingagents.dataflows.interface import route_to_vendor


@tool
def search_news(
    query: Annotated[str, "Free-text search query — a theme, sector, geography, or event"],
    curr_date: Annotated[Optional[str], "Anchor date in yyyy-mm-dd; articles after it are dropped"] = None,
    look_back_days: Annotated[Optional[int], "Days to look back; omit to use the configured default"] = None,
    limit: Annotated[Optional[int], "Max articles to return; omit to use the configured default"] = None,
) -> str:
    """
    Search recent news by free-text query rather than by ticker.
    Use this to work a mandate or theme (e.g. "environment in Japan",
    "Nordic industrials consolidation") or to check an event's coverage.
    Uses the configured search_news vendor (google_news by default).

    Returns:
        str: Formatted headlines with source, date, and link.
    """
    return route_to_vendor("search_news", query, curr_date, look_back_days, limit)


@tool
def get_ticker_snapshot(
    ticker: Annotated[str, "Ticker symbol to validate, incl. exchange suffix if non-US (e.g. 6501.T)"],
) -> str:
    """
    Validate a candidate ticker and return a tradability snapshot:
    name, exchange, currency, last price, market cap, average daily
    volume and value traded, 52-week range, sector, and country.
    Call this for every candidate before putting it in an ideas book —
    a name that does not resolve here is unverified.

    Returns:
        str: Formatted snapshot, or an explicit unresolved-ticker notice.
    """
    return route_to_vendor("get_ticker_snapshot", ticker)


@tool
def get_earnings_calendar(
    ticker: Annotated[str, "Ticker symbol, incl. exchange suffix if non-US"],
    curr_date: Annotated[Optional[str], "Anchor date in yyyy-mm-dd separating upcoming from past; omit for today"] = None,
) -> str:
    """
    Retrieve upcoming and recent earnings dates for a ticker — the
    primary source of dated, verifiable catalysts. An idea whose
    catalyst does not appear here (or in news) is undated.

    Returns:
        str: Upcoming and recent earnings dates with EPS estimates
        where available.
    """
    return route_to_vendor("get_earnings_calendar", ticker, curr_date)
