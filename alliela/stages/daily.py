"""The daily Portfolio Management loop — "origination deliberates,
management executes discipline." Fast, zero debate; anything that
needs arguing escalates back through origination.

Shape (per the flow spec): four intelligence duties — Market Context
(book-level), Daily Risk Report (book-level), Thesis Check
(per-position: the dated kill criteria evaluated, decidable not
vibes), P&L Attribution (move vs thesis expectation, never raw P&L) —
converge on the PM's per-position Position Verdicts (Hold · Add ·
Trim · Exit · Escalate; cannot originate names), then the book-level
Portfolio Review (the loop's ONLY deep-think call) binds the Rebalance
Instruction, then the deterministic daily Compliance gate, then
Execution (fills = the only PMS write; handled by the pipeline/runner).

Real marks: every position gets a fresh verified snapshot; movement is
judged from real prices against (possibly seeded) cost bases — the
run's documents state data status honestly."""
import json

from alliela.documents import (DailyPortfolioNote, DailyRiskReport,
                               MarketContextBrief, PnLAttribution,
                               PositionVerdict, ThesisCheckResult,
                               thesis_sheet_html, verdicts_html)
from alliela.market import context_pack, ticker_snapshot
from alliela.structured import ask_validated

STAGE_INTEL = "Intelligence Duties"
STAGE_VERDICTS = "Position Verdicts"
STAGE_REVIEW = "Portfolio Review"


def run_daily(ctx, llm):
    """Returns (documents, intel_calls, verdict_calls, review_calls,
    note). The pipeline handles compliance + execution from the
    note's rebalance legs."""
    docs = []
    intel_calls, verdict_calls, review_calls = [], [], []
    book = ctx.book or []
    snapshots = {p["ticker"]: ticker_snapshot(p["ticker"])
                 for p in book}
    news = context_pack(["global markets today",
                         "energy transition sector"], per_query=8)
    book_json = json.dumps(book, indent=1, default=str)
    snaps_json = json.dumps(snapshots, indent=1)

    def ask(agent, system, user, schema_cls, calls,
            model=None, reasoning=None):
        return ask_validated(
            ctx, llm, agent=agent, stage=STAGE_INTEL
            if calls is intel_calls else
            (STAGE_VERDICTS if calls is verdict_calls
             else STAGE_REVIEW),
            system=system, user=user,
            validate=schema_cls.model_validate,
            schema_json=json.dumps(schema_cls.model_json_schema()),
            model=model, reasoning=reasoning, calls=calls)

    honesty = ("Data status: position cost bases and thesis notes may "
               "be seeded mock (the fund's backstory); the snapshots "
               "are REAL prices fetched now. State this distinction "
               "where it matters; never dress fiction as fact.")

    # 1 — Market Context (book-level)
    mkt = ask(
        "Market Context",
        "You are the Market Context duty of the daily loop — the "
        "outside world, one pass, whole book. Work only from the "
        "injected headlines and snapshots. " + honesty
        + " Return STRICT JSON matching:\n"
        + json.dumps(MarketContextBrief.model_json_schema(), indent=1),
        f"As-of: {ctx.trade_date}.\n\nHeadlines:\n{news}\n\n"
        f"The book:\n{book_json}\n\nSnapshots (real):\n{snaps_json}",
        MarketContextBrief, intel_calls)
    docs.append(("market-context", "Market Context Brief", "output",
                 mkt.to_html("Market Context Brief"),
                 {"agent": "Market Context", "stage": STAGE_INTEL,
                  "structured": mkt.model_dump()}))

    # 2 — Daily Risk Report (book-level)
    risk = ask(
        "Risk Report",
        "You are the Daily Risk Report duty — the three origination "
        "risk lenses re-checked daily (liquidity, concentration, "
        "drawdown; one risk language with origination) plus the "
        "squeeze watch on every short. Judge from the book and the "
        "real snapshots; name numbers. " + honesty
        + " Return STRICT JSON matching:\n"
        + json.dumps(DailyRiskReport.model_json_schema(), indent=1),
        f"As-of: {ctx.trade_date}.\n\nThe book:\n{book_json}\n\n"
        f"Snapshots (real):\n{snaps_json}\n\nMarket context:\n"
        + mkt.model_dump_json(indent=1),
        DailyRiskReport, intel_calls)
    docs.append(("daily-risk", "Daily Risk Report", "output",
                 risk.to_html("Daily Risk Report"),
                 {"agent": "Risk Report", "stage": STAGE_INTEL,
                  "structured": risk.model_dump()}))

    # 3 — Thesis Check, once per live position
    checks = []
    for p in book:
        c = ask(
            "Thesis Check",
            "You are the Thesis Check duty, evaluating ONE position's "
            "dated kill criteria: fired / approaching / not_fired — "
            "decidable, not vibes. If the thesis data available is too "
            "thin to decide, say 'undecidable' and name what is "
            "missing (that is a process finding, not a failure). "
            + honesty + " Return STRICT JSON matching:\n"
            + json.dumps(ThesisCheckResult.model_json_schema(),
                         indent=1),
            f"As-of: {ctx.trade_date}.\n\nThe position:\n"
            f"{json.dumps(p, indent=1, default=str)}\n\n"
            f"Real snapshot:\n"
            f"{json.dumps(snapshots.get(p['ticker']), indent=1)}",
            ThesisCheckResult, intel_calls)
        checks.append(c)
    docs.append(("thesis-status", "Thesis Status Sheet", "output",
                 thesis_sheet_html("Thesis Status Sheet", checks),
                 {"agent": "Thesis Check", "stage": STAGE_INTEL,
                  "structured": [c.model_dump() for c in checks]}))

    # 4 — P&L Attribution (one pass, whole book)
    pnl = ask(
        "P&L Review",
        "You are the P&L Attribution duty. For each position: the "
        "move against its THESIS EXPECTATION, never raw P&L — entry "
        "price is sunk; up can be off-thesis, down can be on-path. "
        "Use the real snapshots for current prices. " + honesty
        + " Return STRICT JSON matching:\n"
        + json.dumps(PnLAttribution.model_json_schema(), indent=1),
        f"As-of: {ctx.trade_date}.\n\nThe book:\n{book_json}\n\n"
        f"Snapshots (real):\n{snaps_json}\n\nFactor context:\n"
        + mkt.model_dump_json(indent=1),
        PnLAttribution, intel_calls)
    docs.append(("pnl-attribution", "P&L Attribution", "output",
                 pnl.to_html("P&L Attribution"),
                 {"agent": "P&L Review", "stage": STAGE_INTEL,
                  "structured": pnl.model_dump()}))

    # 5 — Position Verdicts, once per live position
    checks_by_ticker = {c.ticker: c for c in checks}
    pnl_by_ticker = {r.ticker: r.note for r in pnl.rows}
    verdicts = []
    for p in book:
        t = p["ticker"]
        v = ask(
            "Position Review",
            "You are the PM's Position Review duty for ONE position: "
            "Hold · Add · Trim · Exit — quick think, no debate. You "
            "cannot originate names; an Add beyond the loop's 2% "
            "guardrail must be 'escalate' (reroutes to origination). "
            "A fired kill criterion demands action or an explicit "
            "thesis amendment. " + honesty
            + " Return STRICT JSON matching:\n"
            + json.dumps(PositionVerdict.model_json_schema(),
                         indent=1),
            f"As-of: {ctx.trade_date}.\n\nThe position:\n"
            f"{json.dumps(p, indent=1, default=str)}\n\n"
            f"Thesis check: "
            f"{checks_by_ticker[t].model_dump_json() if t in checks_by_ticker else '(none)'}"
            f"\nP&L note: {pnl_by_ticker.get(t, '(none)')}\n"
            f"Risk report breaches: "
            f"{json.dumps(risk.breaches)}",
            PositionVerdict, verdict_calls)
        verdicts.append(v)
    docs.append(("position-verdicts", "Position Verdicts", "output",
                 verdicts_html("Position Verdicts", verdicts),
                 {"agent": "Position Review", "stage": STAGE_VERDICTS,
                  "structured": [v.model_dump() for v in verdicts]}))

    # 6 — Portfolio Review (the loop's only deep-think call)
    note = ask(
        "Portfolio Review",
        "You are the Portfolio Review — the daily loop's only "
        "deep-think seat, mirroring origination's judgment level. "
        "Read every duty report and every verdict; override any "
        "verdict the PORTFOLIO disagrees with (name it and why); own "
        "the drawdown-state rules and gross/net/cash targets; bind "
        "the Rebalance Instruction (empty is a first-class answer); "
        "fire re-underwrite or new-idea triggers toward origination "
        "where warranted. Loop guardrails bind you: daily turnover "
        "≤ 10% NAV, ≤ 2% size change per name without re-underwrite, "
        "no new names. " + honesty
        + " Return STRICT JSON matching:\n"
        + json.dumps(DailyPortfolioNote.model_json_schema(), indent=1),
        f"As-of: {ctx.trade_date}.\n\nThe mandate:\n{ctx.mandate_text}"
        f"\n\nThe book:\n{book_json}\n\nMarket context:\n"
        + mkt.model_dump_json(indent=1)
        + "\n\nRisk report:\n" + risk.model_dump_json(indent=1)
        + "\n\nThesis checks:\n"
        + json.dumps([c.model_dump() for c in checks], indent=1)
        + "\n\nP&L attribution:\n" + pnl.model_dump_json(indent=1)
        + "\n\nPosition verdicts:\n"
        + json.dumps([v.model_dump() for v in verdicts], indent=1),
        DailyPortfolioNote, review_calls, model=ctx.deep_model,
        reasoning={"max_tokens": 2048})
    docs.append(("portfolio-note", "Daily Portfolio Note", "output",
                 note.to_html("Daily Portfolio Note"),
                 {"agent": "Portfolio Review", "stage": STAGE_REVIEW,
                  "structured": note.model_dump()}))

    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, intel_calls, verdict_calls, review_calls, note
