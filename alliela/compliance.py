"""The Compliance gate — deterministic rule-checking, deliberately NOT
an LLM. Checks the Dealing Instruction against the mandate's typed
restrictions, the signed RiskConstraints, and the book at order
release. No judgment, no waivers; a failed check returns the decision,
not the order.

Typed mandate limits are encoded here and must match MANDATE_DOC
(web/pages/home.py) — if the mandate changes, change these together.
Rules that need data the gate can't compute mechanically yet (VaR,
top-5 at market) are reported as not-evaluable (ok=None), never
silently skipped."""

# Fund 1 typed restrictions (mirrors MANDATE_DOC sections 06-08)
MAX_SINGLE_POSITION_COST_PCT = 12.0
MAX_COUNTRY_GROSS_PCT = 25.0          # single non-US country
MAX_GROSS_SHORT_PCT = 20.0
MAX_SINGLE_SHORT_PCT = 5.0
CASH_FLOOR_PCT = 1.0

# Daily-loop guardrails (the loop executes discipline, it does not
# deliberate — anything bigger reroutes through origination)
MAX_DAILY_TURNOVER_PCT = 10.0         # sum of legs per day
MAX_SIZE_CHANGE_PCT = 2.0             # per name without re-underwrite

JAPAN_SUFFIX = ".T"


def check_instruction(instruction, decision, constraints, book,
                      funding=None):
    """Returns (checks, passed). Each check: {rule, observed, ok}
    where ok is True/False/None (not evaluable)."""
    checks = []

    def add(rule, observed, ok):
        checks.append({"rule": rule, "observed": observed, "ok": ok})

    entry_legs = [l for l in instruction.legs if l.purpose == "entry"]
    entry_size = sum(l.size_pct_nav for l in entry_legs)
    weights = {p["ticker"]: float(p["weight_pct"]) for p in book}

    # 1. Risk cap — the signed constraint binds
    cap = constraints.max_position_pct_nav
    existing = sum(weights.get(l.ticker, 0.0) for l in entry_legs)
    add(f"RiskConstraints position cap ≤ {cap:g}% NAV",
        f"entry {entry_size:g}% + existing {existing:g}% = "
        f"{entry_size + existing:g}%",
        entry_size + abs(existing) <= cap + 1e-9)

    # 2. Mandate single-position cap at cost
    add(f"Mandate max single position ≤ "
        f"{MAX_SINGLE_POSITION_COST_PCT:g}% at cost",
        f"{entry_size + abs(existing):g}%",
        entry_size + abs(existing) <= MAX_SINGLE_POSITION_COST_PCT)

    # 3. Country gross (Japan proxy: .T tickers)
    jp_book = sum(abs(float(p["weight_pct"])) for p in book
                  if str(p["ticker"]).endswith(JAPAN_SUFFIX))
    jp_delta = sum(l.size_pct_nav for l in entry_legs
                   if l.ticker.endswith(JAPAN_SUFFIX))
    jp_trims = sum(l.size_pct_nav for l in instruction.legs
                   if l.purpose == "funding_trim"
                   and l.ticker.endswith(JAPAN_SUFFIX))
    jp_after = jp_book + jp_delta - jp_trims
    add(f"Mandate single non-US country gross ≤ "
        f"{MAX_COUNTRY_GROSS_PCT:g}%",
        f"Japan gross after instruction ≈ {jp_after:.1f}%",
        jp_after <= MAX_COUNTRY_GROSS_PCT)

    # 4. Shorting rules
    is_short = decision.action == "buy" and any(
        l.side == "sell" and l.purpose == "entry"
        for l in instruction.legs)
    short_entry = sum(l.size_pct_nav for l in entry_legs
                      if l.side == "sell")
    if short_entry:
        gross_short = sum(abs(float(p["weight_pct"])) for p in book
                          if p["direction"] == "S") + short_entry
        add(f"Mandate max single short ≤ {MAX_SINGLE_SHORT_PCT:g}%",
            f"{short_entry:g}%",
            short_entry <= MAX_SINGLE_SHORT_PCT)
        add(f"Mandate gross short ≤ {MAX_GROSS_SHORT_PCT:g}%",
            f"≈ {gross_short:.1f}% after entry",
            gross_short <= MAX_GROSS_SHORT_PCT)
    else:
        add("Shorting rules", "no short legs — n/a", True)

    # 5. Cash floor (needs the funding plan's arithmetic)
    if funding is not None:
        add(f"Mandate cash floor ≥ {CASH_FLOOR_PCT:g}%",
            f"funding plan leaves {funding.resulting_cash_pct:g}%",
            funding.resulting_cash_pct >= CASH_FLOOR_PCT)
    else:
        add(f"Mandate cash floor ≥ {CASH_FLOOR_PCT:g}%",
            "no funding plan supplied", None)

    # 6. Stops present when constraints demand them
    add("Mandatory stops placed",
        f"{len(instruction.stops_to_place)} stop(s) in instruction vs "
        f"{len(constraints.mandatory_stops)} required",
        len(instruction.stops_to_place) >=
        len(constraints.mandatory_stops) > 0
        or len(constraints.mandatory_stops) == 0)

    # 7. Not mechanically evaluable yet — reported, not skipped
    add("Top-5 concentration ≤ 65% at market", "needs marked prices",
        None)
    add("1-day 95% VaR ≤ 2.5%", "needs a risk model", None)

    passed = all(c["ok"] is not False for c in checks)
    return checks, passed


def check_daily(legs, book):
    """The daily-loop compliance gate: mandate rules + loop guardrails
    on the Rebalance Instruction's legs. Deterministic, no LLM; FAIL
    bounces the note back to Portfolio Review."""
    checks = []

    def add(rule, observed, ok):
        checks.append({"rule": rule, "observed": observed, "ok": ok})

    tickers_in_book = {p["ticker"] for p in book}
    weights = {p["ticker"]: float(p["weight_pct"]) for p in book}

    turnover = sum(l.size_pct_nav for l in legs)
    add(f"Loop guardrail: daily turnover ≤ {MAX_DAILY_TURNOVER_PCT:g}%",
        f"{turnover:g}%", turnover <= MAX_DAILY_TURNOVER_PCT)

    new_names = [l.ticker for l in legs
                 if l.ticker not in tickers_in_book]
    add("Loop guardrail: no new names (origination owns entries)",
        f"new: {new_names or 'none'}", not new_names)

    oversize = [l.ticker for l in legs
                if l.size_pct_nav > MAX_SIZE_CHANGE_PCT]
    add(f"Loop guardrail: size change ≤ {MAX_SIZE_CHANGE_PCT:g}% per "
        f"name without re-underwrite",
        f"over: {oversize or 'none'}", not oversize)

    for l in legs:
        if l.side == "sell" and l.ticker in weights \
                and weights[l.ticker] > 0:
            if l.size_pct_nav > weights[l.ticker] + 1e-9:
                add("Sells cannot exceed the held weight",
                    f"{l.ticker}: sell {l.size_pct_nav:g}% vs held "
                    f"{weights[l.ticker]:g}%", False)

    shorts_after = {}
    for p in book:
        if p["direction"] == "S":
            shorts_after[p["ticker"]] = abs(float(p["weight_pct"]))
    for l in legs:
        if l.side == "sell" and shorts_after.get(l.ticker) is not None:
            shorts_after[l.ticker] += l.size_pct_nav
    gross_short = sum(shorts_after.values())
    add(f"Mandate gross short ≤ {MAX_GROSS_SHORT_PCT:g}%",
        f"≈ {gross_short:.1f}% after legs",
        gross_short <= MAX_GROSS_SHORT_PCT)

    passed = all(c["ok"] is not False for c in checks)
    return checks, passed
