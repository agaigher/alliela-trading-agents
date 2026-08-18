"""The Compliance gate — deterministic rule-checking, deliberately NOT
an LLM. Checks the Dealing Instruction against the mandate's typed
restrictions, the signed RiskConstraints, and the book at order
release. No judgment, no waivers; a failed check returns the decision,
not the order.

Typed mandate limits are **data**, carried on `RunContext.restrictions`
and supplied per fund by the runner. They were module constants while
one house fund existed; once a fund can be created with its own
mandate, constants would mean the gate silently enforced the house
fund's numbers against somebody else's rules — the page would claim
their mandate governs while the gate ignored it.

The constants survive as `DEFAULT_RESTRICTIONS`: the house fund's
values, and the fallback when a runner supplies nothing. They still
mirror MANDATE_DOC (web/pages/home.py) — change them together.

Rules that need data the gate can't compute mechanically yet (VaR,
top-5 at market) are reported as not-evaluable (ok=None), never
silently skipped."""
from dataclasses import dataclass, field

JAPAN_SUFFIX = ".T"


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
    max_gross_short_pct: float = 20.0
    max_single_short_pct: float = 5.0
    cash_floor_pct: float = 1.0
    shorting_permitted: bool = True
    # Country gross caps keyed by ticker suffix — the honest
    # generalisation of the old hardcoded ".T is Japan" proxy. Each
    # entry: {"suffix": ".T", "country": "Japan", "max_pct": 25.0}.
    country_gross_caps: tuple = ()
    # Daily-loop guardrails (the loop executes discipline, it does not
    # deliberate — anything bigger reroutes through origination)
    max_daily_turnover_pct: float = 10.0
    max_size_change_pct: float = 2.0
    # Which limits are advisory. Maps a field name above to "hard" or
    # "soft"; anything unlisted is HARD. The default direction is
    # deliberate — a mandate that forgets to classify a limit gets the
    # blocking one, so a limit can only become advisory by saying so.
    #
    # hard  -> breach fails the gate; the instruction returns to the PM
    # soft  -> breach is recorded on the Compliance Record and the run
    #          proceeds. Real mandates call this comply-or-explain: a
    #          guideline a market move can breach without anyone
    #          trading should not halt the fund, but it must never pass
    #          silently either.
    limit_types: dict = field(default_factory=dict)

    def kind(self, field_name):
        return "soft" if self.limit_types.get(field_name) == "soft" \
            else "hard"

    @classmethod
    def from_dict(cls, data):
        """Build from stored JSON, ignoring unknown keys so a mandate
        written by a newer schema never crashes an older engine."""
        if not data:
            return DEFAULT_RESTRICTIONS
        if isinstance(data, cls):
            return data
        known = {f for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in data.items() if k in known}
        caps = kwargs.get("country_gross_caps")
        if caps:
            kwargs["country_gross_caps"] = tuple(
                {"suffix": c.get("suffix", ""),
                 "country": c.get("country", "?"),
                 "max_pct": float(c.get("max_pct", 100.0)),
                 # a per-cap override must survive normalisation, or a
                 # mandate that declares one cap advisory silently gets
                 # a blocking one
                 "type": "soft" if c.get("type") == "soft" else "hard"}
                for c in caps)
        return cls(**kwargs)


# The house fund's values, and the fallback when a runner supplies
# nothing (local drivers, older callers, tests).
DEFAULT_RESTRICTIONS = Restrictions(
    country_gross_caps=({"suffix": JAPAN_SUFFIX, "country": "Japan",
                         "max_pct": 25.0},),
)


def _passed(checks):
    """Released when no HARD limit failed. Soft breaches ride along on
    the record — comply-or-explain, not comply-or-halt."""
    return not any(c["ok"] is False and c.get("severity") != "soft"
                   for c in checks)


def soft_breaches(checks):
    """The soft limits an instruction broke — the material the
    Retrospective judges when asking whether the fund keeps explaining
    away the same guideline."""
    return [c for c in checks
            if c["ok"] is False and c.get("severity") == "soft"]


def check_instruction(instruction, decision, constraints, book,
                      funding=None, restrictions=None):
    """Returns (checks, passed). Each check: {rule, observed, ok}
    where ok is True/False/None (not evaluable).

    `restrictions` is the fund's typed mandate limits; omitted, the
    house defaults apply."""
    r = Restrictions.from_dict(restrictions)
    checks = []

    def add(rule, observed, ok, kind="hard"):
        """severity records WHY a failure does or doesn't block, so a
        blocked trade and an explained one stay distinguishable."""
        checks.append({"rule": rule, "observed": observed, "ok": ok,
                       "severity": "n/e" if ok is None else kind})

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
        f"{r.max_single_position_cost_pct:g}% at cost",
        f"{entry_size + abs(existing):g}%",
        entry_size + abs(existing) <= r.max_single_position_cost_pct,
        r.kind("max_single_position_cost_pct"))

    # 3. Country gross — one check per configured cap, by ticker
    #    suffix. No caps configured means nothing to enforce, which is
    #    stated rather than passed silently.
    if r.country_gross_caps:
        for cap_rule in r.country_gross_caps:
            suffix = cap_rule["suffix"]
            in_book = sum(abs(float(p["weight_pct"])) for p in book
                          if str(p["ticker"]).endswith(suffix))
            delta = sum(l.size_pct_nav for l in entry_legs
                        if l.ticker.endswith(suffix))
            trims = sum(l.size_pct_nav for l in instruction.legs
                        if l.purpose == "funding_trim"
                        and l.ticker.endswith(suffix))
            after = in_book + delta - trims
            add(f"Mandate {cap_rule['country']} gross ≤ "
                f"{cap_rule['max_pct']:g}%",
                f"{cap_rule['country']} gross after instruction "
                f"≈ {after:.1f}%",
                after <= cap_rule["max_pct"],
                "soft" if cap_rule.get("type") == "soft"
                else r.kind("country_gross_caps"))
    else:
        add("Country gross caps", "none defined in this mandate", None)

    # 4. Shorting rules
    short_entry = sum(l.size_pct_nav for l in entry_legs
                      if l.side == "sell")
    if short_entry:
        if not r.shorting_permitted:
            add("Mandate permits shorting", "mandate forbids shorts, "
                f"instruction shorts {short_entry:g}%", False,
                r.kind("shorting_permitted"))
        gross_short = sum(abs(float(p["weight_pct"])) for p in book
                          if p["direction"] == "S") + short_entry
        add(f"Mandate max single short ≤ {r.max_single_short_pct:g}%",
            f"{short_entry:g}%",
            short_entry <= r.max_single_short_pct,
            r.kind("max_single_short_pct"))
        add(f"Mandate gross short ≤ {r.max_gross_short_pct:g}%",
            f"≈ {gross_short:.1f}% after entry",
            gross_short <= r.max_gross_short_pct,
            r.kind("max_gross_short_pct"))
    else:
        add("Shorting rules", "no short legs — n/a", True)

    # 5. Cash floor (needs the funding plan's arithmetic)
    if funding is not None:
        add(f"Mandate cash floor ≥ {r.cash_floor_pct:g}%",
            f"funding plan leaves {funding.resulting_cash_pct:g}%",
            funding.resulting_cash_pct >= r.cash_floor_pct,
            r.kind("cash_floor_pct"))
    else:
        add(f"Mandate cash floor ≥ {r.cash_floor_pct:g}%",
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

    passed = _passed(checks)
    return checks, passed


def check_daily(legs, book, restrictions=None):
    """The daily-loop compliance gate: mandate rules + loop guardrails
    on the Rebalance Instruction's legs. Deterministic, no LLM; FAIL
    bounces the note back to Portfolio Review."""
    r = Restrictions.from_dict(restrictions)
    checks = []

    def add(rule, observed, ok, kind="hard"):
        """severity records WHY a failure does or doesn't block, so a
        blocked trade and an explained one stay distinguishable."""
        checks.append({"rule": rule, "observed": observed, "ok": ok,
                       "severity": "n/e" if ok is None else kind})

    tickers_in_book = {p["ticker"] for p in book}
    weights = {p["ticker"]: float(p["weight_pct"]) for p in book}

    turnover = sum(l.size_pct_nav for l in legs)
    add(f"Loop guardrail: daily turnover ≤ {r.max_daily_turnover_pct:g}%",
        f"{turnover:g}%", turnover <= r.max_daily_turnover_pct,
        r.kind("max_daily_turnover_pct"))

    new_names = [l.ticker for l in legs
                 if l.ticker not in tickers_in_book]
    add("Loop guardrail: no new names (origination owns entries)",
        f"new: {new_names or 'none'}", not new_names)

    oversize = [l.ticker for l in legs
                if l.size_pct_nav > r.max_size_change_pct]
    add(f"Loop guardrail: size change ≤ {r.max_size_change_pct:g}% per "
        f"name without re-underwrite",
        f"over: {oversize or 'none'}", not oversize,
        r.kind("max_size_change_pct"))

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
    add(f"Mandate gross short ≤ {r.max_gross_short_pct:g}%",
        f"≈ {gross_short:.1f}% after legs",
        gross_short <= r.max_gross_short_pct,
        r.kind("max_gross_short_pct"))

    passed = _passed(checks)
    return checks, passed
