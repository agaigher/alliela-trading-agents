"""The Compliance gate — deterministic rule-checking, deliberately NOT
an LLM. Checks the Dealing Instruction against the platform rules, the
mandate's typed restrictions, the signed RiskConstraints, and the book
at order release. No judgment, no waivers; a failed check returns the
decision, not the order.

Two layers, both hard:

- **Platform rules** (alliela/universe.py): US-listed common stock on
  NYSE/Nasdaq, long only. They bind every fund and no mandate can
  loosen them.
- **Mandate limits**, which are data carried on `RunContext.restrictions`
  and supplied per fund by the runner. Since 10 Nov 2026 there are four,
  every one hard: max single position, cash floor, max positions and the
  liquidity floor (that last one enforced at Selection, not here). The
  short limits, the exposure bands, the country caps and the soft/hard
  choice all went when the platform went long-only in one market.

`DEFAULT_RESTRICTIONS` is the fallback when a runner supplies nothing.

Rules that need data the gate can't compute mechanically yet (VaR,
top-5 at market) are reported as not-evaluable (ok=None), never
silently skipped."""
from dataclasses import dataclass

from alliela.universe import us_ticker_format


@dataclass(frozen=True)
class Restrictions:
    """A mandate's machine-checkable limits.

    Every field is something the gate can evaluate without judgment.
    Prose that needs interpretation stays in the mandate text for the
    agents to read — it does not belong here, because a rule the gate
    cannot decide mechanically is a rule it must report as
    not-evaluable rather than pretend to enforce.
    """
    max_single_position_cost_pct: float = 12.0
    cash_floor_pct: float = 1.0
    max_positions: int = 20
    # Liquidity floor in USD of average daily value traded. Enforced by
    # the Selection Committee's feasibility lens, not this gate — the
    # gate never sees ADV. It lives here because it is a mandate limit.
    min_adv_usd: float = 8_000_000.0
    # Daily-loop guardrails (the loop executes discipline, it does not
    # deliberate — anything bigger reroutes through origination). Fixed
    # engine defaults: no mandate exposes them since 10 Nov 2026, but a
    # stored value is still honoured.
    max_daily_turnover_pct: float = 10.0
    max_size_change_pct: float = 2.0

    @classmethod
    def from_dict(cls, data):
        """Build from stored JSON, ignoring unknown keys — so a mandate
        written by a newer schema never crashes an older engine, and one
        written before the long-only change (short limits, country caps,
        limit_types) still loads, its obsolete keys simply unread."""
        if not data:
            return DEFAULT_RESTRICTIONS
        if isinstance(data, cls):
            return data
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in data.items()
                      if k in known and v is not None})


DEFAULT_RESTRICTIONS = Restrictions()


def _passed(checks):
    """Released when nothing failed. Every check is hard."""
    return not any(c["ok"] is False for c in checks)


def _adder(checks):
    def add(rule, observed, ok):
        checks.append({"rule": rule, "observed": observed, "ok": ok,
                       "severity": "n/e" if ok is None else "hard"})
    return add


def check_instruction(instruction, decision, constraints, book,
                      funding=None, restrictions=None):
    """Returns (checks, passed). Each check: {rule, observed, ok}
    where ok is True/False/None (not evaluable).

    `restrictions` is the fund's typed mandate limits; omitted, the
    defaults apply."""
    r = Restrictions.from_dict(restrictions)
    checks = []
    add = _adder(checks)

    entry_legs = [l for l in instruction.legs if l.purpose == "entry"]
    entry_size = sum(l.size_pct_nav for l in entry_legs)
    weights = {p["ticker"]: float(p["weight_pct"]) for p in book}

    # 0. Platform rules — before any mandate number, because no mandate
    #    can loosen them.
    short_legs = [l.ticker for l in entry_legs if l.side != "buy"]
    add("Platform: long only",
        f"short entry legs: {short_legs or 'none'}", not short_legs)
    foreign = sorted({l.ticker for l in instruction.legs
                      if not us_ticker_format(l.ticker)})
    add("Platform: US-listed stock (NYSE/Nasdaq)",
        f"non-US tickers: {foreign or 'none'}", not foreign)

    # 1. Risk cap — the signed constraint binds
    cap = constraints.max_position_pct_nav
    existing = sum(weights.get(l.ticker, 0.0) for l in entry_legs)
    add(f"RiskConstraints position cap ≤ {cap:g}% NAV",
        f"entry {entry_size:g}% + existing {existing:g}% = "
        f"{entry_size + existing:g}%",
        entry_size + abs(existing) <= cap + 1e-9)

    # 2. Mandate single-position cap at cost
    add(f"Mandate max single position ≤ "
        f"{r.max_single_position_cost_pct:g}% at cost",
        f"{entry_size + abs(existing):g}%",
        entry_size + abs(existing) <= r.max_single_position_cost_pct)

    # 3. Cash floor (needs the funding plan's arithmetic)
    if funding is not None:
        add(f"Mandate cash floor ≥ {r.cash_floor_pct:g}%",
            f"funding plan leaves {funding.resulting_cash_pct:g}%",
            funding.resulting_cash_pct >= r.cash_floor_pct)
    else:
        add(f"Mandate cash floor ≥ {r.cash_floor_pct:g}%",
            "no funding plan supplied", None)

    # 4. Name count after the instruction
    after = dict(weights)
    for l in instruction.legs:
        delta = l.size_pct_nav if l.side == "buy" else -l.size_pct_nav
        if l.purpose == "funding_trim":   # always reduces a held long
            delta = -abs(l.size_pct_nav)
        after[l.ticker] = after.get(l.ticker, 0.0) + delta
    held = [t for t, w in after.items() if w > 1e-9]
    add(f"Mandate max positions <= {r.max_positions:g}",
        f"{len(held)} names after instruction",
        len(held) <= r.max_positions)

    # 5. Stops present when constraints demand them
    add("Mandatory stops placed",
        f"{len(instruction.stops_to_place)} stop(s) in instruction vs "
        f"{len(constraints.mandatory_stops)} required",
        len(instruction.stops_to_place) >=
        len(constraints.mandatory_stops) > 0
        or len(constraints.mandatory_stops) == 0)

    # 6. Not mechanically evaluable yet — reported, not skipped
    add("Top-5 concentration ≤ 65% at market", "needs marked prices",
        None)
    add("1-day 95% VaR ≤ 2.5%", "needs a risk model", None)

    return checks, _passed(checks)


def check_daily(legs, book, restrictions=None):
    """The daily-loop compliance gate: platform rules + loop guardrails
    on the Rebalance Instruction's legs. Deterministic, no LLM; FAIL
    bounces the note back to Portfolio Review."""
    r = Restrictions.from_dict(restrictions)
    checks = []
    add = _adder(checks)

    tickers_in_book = {p["ticker"] for p in book}
    weights = {p["ticker"]: float(p["weight_pct"]) for p in book}

    turnover = sum(l.size_pct_nav for l in legs)
    add(f"Loop guardrail: daily turnover ≤ {r.max_daily_turnover_pct:g}%",
        f"{turnover:g}%", turnover <= r.max_daily_turnover_pct)

    new_names = [l.ticker for l in legs
                 if l.ticker not in tickers_in_book]
    add("Loop guardrail: no new names (origination owns entries)",
        f"new: {new_names or 'none'}", not new_names)

    oversize = [l.ticker for l in legs
                if l.size_pct_nav > r.max_size_change_pct]
    add(f"Loop guardrail: size change ≤ {r.max_size_change_pct:g}% per "
        f"name without re-underwrite",
        f"over: {oversize or 'none'}", not oversize)

    # A sell larger than the held long would open a short.
    oversold = [f"{l.ticker}: sell {l.size_pct_nav:g}% vs held "
                f"{max(weights.get(l.ticker, 0.0), 0.0):g}%"
                for l in legs if l.side == "sell"
                and l.size_pct_nav > max(weights.get(l.ticker, 0.0), 0.0)
                + 1e-9]
    add("Platform: long only (a sell cannot exceed the held weight)",
        f"over: {oversold or 'none'}", not oversold)

    return checks, _passed(checks)
