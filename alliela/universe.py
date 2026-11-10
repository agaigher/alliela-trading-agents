"""The platform universe: US-listed common stock, long only.

A platform rule, not a mandate setting: every fund trades it and no
mandate can loosen it. Checked deterministically, from the Yahoo chart
meta the Selection stage already fetches, and again by the gate on the
ticker itself. A prompt can be argued with; this cannot.

ADRs pass: they are US-listed equity. ETFs, funds, options, preferreds
and every non-US listing do not.
"""
import re

# Yahoo's chart `exchangeName` codes for the two venues.
US_EXCHANGES = {
    "NYQ": "NYSE",
    "NMS": "Nasdaq",   # Global Select
    "NGM": "Nasdaq",   # Global Market
    "NCM": "Nasdaq",   # Capital Market
}
INSTRUMENT = "EQUITY"

# A US ticker as Yahoo writes it: 1-5 letters, optionally a share class
# after a hyphen (BRK-B). Any exchange suffix (.T, .DE, .L) fails.
_US_TICKER = re.compile(r"^[A-Z]{1,5}(-[A-Z])?$")

RULE_TEXT = ("PLATFORM RULES (bind every fund, override any mandate "
             "text): US-listed common stock on NYSE or Nasdaq only "
             "(ADRs count; no ETFs, funds, options, preferreds or "
             "non-US listings); long positions only, never a short.")


def us_ticker_format(ticker):
    return bool(_US_TICKER.match(str(ticker or "").strip()))


def listing_check(snapshot):
    """(eligible, reason) for a ticker_snapshot dict.

    'data_unavailable' cannot be confirmed either way. The format check
    still runs, so an obviously foreign ticker is refused, but a US-
    shaped ticker is allowed through with the gap stated, the same rule
    the feasibility lens applies to missing data.
    """
    ticker = snapshot.get("ticker", "")
    status = snapshot.get("status")
    if status == "not_found":
        return False, "ticker does not resolve"
    if not us_ticker_format(ticker):
        return False, (f"{ticker} is not a US ticker (exchange suffix "
                       "or malformed); the platform trades NYSE/Nasdaq "
                       "only")
    if status != "ok":
        return True, "listing unverified (data unavailable); format is US"
    kind = snapshot.get("instrument_type") or ""
    code = snapshot.get("exchange_code") or ""
    if kind and kind != INSTRUMENT:
        return False, f"{ticker} is {kind}, not a common stock"
    if code not in US_EXCHANGES:
        venue = snapshot.get("exchange") or code or "unknown venue"
        return False, f"{ticker} lists on {venue}, not NYSE/Nasdaq"
    return True, f"{US_EXCHANGES[code]} {kind or 'listing'}"
