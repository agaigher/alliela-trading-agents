"""Pipeline entry points. Full origination coverage — Tiers 01–09
(Idea Generation → Selection → Analysts → Thesis Desk → Structuring →
Risk panel → PM (Decision·Funding·Instruction) → Compliance gate →
Execution). Each run returns a rollup the runner persists: per-stage
rows, totals, outcome, documents, and — when Execution fills — the
fills for the runner to write to the PMS (the only PMS write)."""
import time

from alliela.compliance import check_instruction
from alliela.documents import compliance_record_html
from alliela.stages.analysts import run_analysts
from alliela.stages.execution import run_execution
from alliela.stages.ideagen import run_ideagen
from alliela.stages.pm import run_pm
from alliela.stages.risk import run_risk
from alliela.stages.selection import run_selection
from alliela.stages.retrospective import run_retrospective as _run_retro
from alliela.stages.structuring import run_structuring
from alliela.stages.thesis import run_thesis


def _fmt_tokens(n):
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(n)


def _stage_row(name, agents, model, calls):
    tok_in = sum(c.usage.get("prompt_tokens", 0) for c in calls)
    tok_out = sum(c.usage.get("completion_tokens", 0) for c in calls)
    reasoning = sum(
        (c.usage.get("completion_tokens_details") or {})
        .get("reasoning_tokens", 0) for c in calls)
    cost = sum(c.cost_usd for c in calls)
    return [name, agents, model.split("/")[-1], len(calls),
            _fmt_tokens(tok_in), _fmt_tokens(tok_out),
            _fmt_tokens(reasoning) if reasoning else "—",
            f"${cost:.2f}"]


def run_origination(ctx, llm):
    """Execute the origination pipeline (tiers 01–02 for now). Returns
    the rollup dict; calls and documents stream to ctx.sink as they
    happen."""
    started = time.monotonic()
    stages, all_calls, all_docs = [], [], []

    docs, calls, combined = run_ideagen(ctx, llm)
    stages.append(_stage_row("Idea Generation", "3 desks + Head",
                             ctx.quick_model, calls))
    all_calls += calls
    all_docs += docs

    docs, calls, brief = run_selection(ctx, llm, combined)
    stages.append(_stage_row("Selection Committee", "3 scorers + Chair",
                             ctx.quick_model, calls))
    all_calls += calls
    all_docs += docs

    thesis = None
    if brief.viable:
        docs, calls, reports = run_analysts(ctx, llm, brief)
        stages.append(_stage_row("Analyst Team", "4 analysts + Lead",
                                 ctx.quick_model, calls))
        all_calls += calls
        all_docs += docs

        docs, calls, thesis = run_thesis(ctx, llm, brief, reports)
        stages.append(_stage_row("Thesis Desk",
                                 "Bull · Bear ×3 + Mgr + Pre-mortem",
                                 ctx.deep_model, calls))
        all_calls += calls
        all_docs += docs

    proposal = None
    constraints = None
    if thesis is not None and thesis.direction != "pass":
        docs, calls, proposal = run_structuring(ctx, llm, thesis,
                                                reports)
        stages.append(_stage_row("Pre-Trade Structuring",
                                 "Trading Desk", ctx.deep_model,
                                 calls))
        all_calls += calls
        all_docs += docs

        docs, calls, constraints = run_risk(ctx, llm, thesis, proposal)
        stages.append(_stage_row("Risk Panel",
                                 "3 lenses + Head of Risk",
                                 ctx.deep_model, calls))
        all_calls += calls
        all_docs += docs

    decision = funding = instruction = report = None
    compliance_passed = None
    if constraints is not None and not constraints.veto:
        docs, calls, decision, funding, instruction = run_pm(
            ctx, llm, thesis, proposal, constraints)
        stages.append(_stage_row("Portfolio Manager",
                                 "Decision · Funding · Instruction",
                                 ctx.pm_model, calls))
        all_calls += calls
        all_docs += docs

    if instruction is not None:
        # Compliance gate — deterministic, no LLM, 0 calls
        checks, compliance_passed = check_instruction(
            instruction, decision, constraints, ctx.book, funding)
        record = compliance_record_html(checks, compliance_passed)
        doc = ("compliance-record", "Compliance Record", "output",
               record, {"agent": "Compliance (rule engine)",
                        "stage": "Compliance",
                        "structured": {"checks": checks,
                                       "passed": compliance_passed}})
        all_docs.append(doc)
        if ctx.sink:
            ctx.sink.on_document(*doc)
        stages.append(["Compliance", "rule engine — no LLM", "—", 0,
                       "—", "—", "—", "$0.00"])

        if compliance_passed:
            docs, calls, report = run_execution(ctx, llm, instruction)
            stages.append(_stage_row("Execution", "Trading Desk",
                                     ctx.quick_model, calls))
            all_calls += calls
            all_docs += docs

    tok_in = sum(c.usage.get("prompt_tokens", 0) for c in all_calls)
    tok_out = sum(c.usage.get("completion_tokens", 0) for c in all_calls)
    reasoning = sum(
        (c.usage.get("completion_tokens_details") or {})
        .get("reasoning_tokens", 0) for c in all_calls)
    cost = sum(c.cost_usd for c in all_calls)
    elapsed = int(time.monotonic() - started)

    prefix = f"“{ctx.tip}” → " if ctx.tip else "Free scan → "
    if thesis is not None:
        if thesis.direction == "pass":
            outcome = (prefix + f"{thesis.ticker} judged — PASS at "
                       f"the Thesis Desk "
                       f"({len(thesis.kill_criteria)} dated re-entry "
                       f"criteria) · {len(all_docs)} docs")
        elif constraints is not None and constraints.veto:
            outcome = (prefix + f"{thesis.ticker} "
                       f"{thesis.direction.upper()} proposal VETOED "
                       f"by the Head of Risk · {len(all_docs)} docs")
        elif report is not None:
            filled = sum(f.size_pct_nav for f in report.fills
                         if f.purpose == "entry")
            outcome = (prefix + f"{thesis.ticker} "
                       f"{decision.action.upper()} "
                       f"{decision.size_pct_nav:g}% NAV · tranche 1 "
                       f"filled ({filled:g}%) · FULL PIPELINE · "
                       f"{len(all_docs)} docs")
        elif compliance_passed is False:
            outcome = (prefix + f"{thesis.ticker} — Compliance FAILED "
                       f"the Dealing Instruction; decision returned · "
                       f"{len(all_docs)} docs")
        elif decision is not None and decision.action == "decline":
            outcome = (prefix + f"{thesis.ticker} — PM DECLINED "
                       f"(no-trade, first-class outcome) · "
                       f"{len(all_docs)} docs")
        elif constraints is not None:
            outcome = (prefix + f"{thesis.ticker} "
                       f"{thesis.direction.upper()} — RiskConstraints "
                       f"signed (cap "
                       f"{constraints.max_position_pct_nav:g}% NAV) · "
                       f"{len(all_docs)} docs")
        elif proposal is not None:
            outcome = (prefix + f"{thesis.ticker} "
                       f"{thesis.direction.upper()} proposal — "
                       f"{proposal.size_pct_nav:g}% NAV staged · "
                       f"{len(all_docs)} docs")
        else:
            outcome = (prefix + f"{thesis.ticker} thesis formed "
                       f"({thesis.direction.upper()}, "
                       f"{len(thesis.kill_criteria)} kill criteria) · "
                       f"{len(all_docs)} docs")
    elif brief.viable:
        outcome = (prefix + f"{brief.ticker} selected "
                   f"({len(combined.candidates)} scored) · "
                   f"{len(all_docs)} docs")
    else:
        outcome = (prefix + "no candidate survived Selection — "
                   "no-trade run (first-class outcome) · "
                   f"{len(all_docs)} docs")

    rollup = {
        "outcome": outcome,
        "calls": len(all_calls),
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "reasoning_tokens": reasoning,
        "cost_usd": round(cost, 4),
        "duration_seconds": elapsed,
        "stages": stages,
        "documents": [{"key": k, "title": t}
                      for k, t, *_ in all_docs],
        # the runner writes these to the PMS — the only PMS write
        "fills": ([f.model_dump() for f in report.fills]
                  if report is not None else []),
        "position_context": ({
            "ticker": thesis.ticker,
            "name": thesis.name,
            "direction": "L" if thesis.direction == "long" else "S",
            "stop": (constraints.mandatory_stops[0]
                     if constraints and constraints.mandatory_stops
                     else ""),
            "kill_note": (f"0 fired · next "
                          f"{thesis.kill_criteria[0].date}"
                          if thesis.kill_criteria else ""),
        } if report is not None else None),
    }
    if ctx.sink:
        ctx.sink.finalize(rollup)
    return rollup


def run_retrospective(ctx, llm):
    """Execute the weekly Retrospective. Returns the rollup; the
    Improvement Backlog inside it is the Developer Agent's work
    order — the seed of the next flow version."""
    started = time.monotonic()
    docs, calls, head = _run_retro(ctx, llm)

    tok_in = sum(c.usage.get("prompt_tokens", 0) for c in calls)
    tok_out = sum(c.usage.get("completion_tokens", 0) for c in calls)
    reasoning = sum(
        (c.usage.get("completion_tokens_details") or {})
        .get("reasoning_tokens", 0) for c in calls)
    cost = sum(c.cost_usd for c in calls)
    elapsed = int(time.monotonic() - started)

    items = sorted(head.backlog.items, key=lambda i: i.rank)
    top = items[0].title if items else "no backlog items"
    outcome = (f"Retrospective → {len(items)} backlog item(s) · "
               f"top: {top} · {len(docs)} docs")

    rollup = {
        "outcome": outcome,
        "calls": len(calls),
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "reasoning_tokens": reasoning,
        "cost_usd": round(cost, 4),
        "duration_seconds": elapsed,
        "stages": [
            _stage_row("Retrospective",
                       "Scorekeeper · Attribution · 3 auditors",
                       ctx.quick_model, calls[:-1]),
            _stage_row("Head of Performance Review", "deep judgment",
                       ctx.deep_model, calls[-1:]),
        ],
        "documents": [{"key": k, "title": t} for k, t, *_ in docs],
        "fills": [],
        "position_context": None,
    }
    if ctx.sink:
        ctx.sink.finalize(rollup)
    return rollup


def run_daily_loop(ctx, llm):
    """Execute the daily Portfolio Management loop. Rebalance legs (if
    any) pass the deterministic daily gate, then Execution turns them
    into fills for the runner's PMS write."""
    from alliela.compliance import check_daily
    from alliela.documents import (DealingInstruction, InstructionLeg,
                                   compliance_record_html)
    from alliela.stages.daily import run_daily
    from alliela.stages.execution import run_execution

    started = time.monotonic()
    stages, all_calls, all_docs = [], [], []

    docs, intel, verdicts_calls, review, note = run_daily(ctx, llm)
    n_pos = len(ctx.book or [])
    stages.append(_stage_row(
        "Intelligence Duties",
        f"Mkt Context · Risk · {n_pos} Thesis Checks · P&L",
        ctx.quick_model, intel))
    stages.append(_stage_row("Position Verdicts", f"PM × {n_pos}",
                             ctx.quick_model, verdicts_calls))
    stages.append(_stage_row("Portfolio Review", "deep think",
                             ctx.deep_model, review))
    all_calls += intel + verdicts_calls + review
    all_docs += docs

    report = None
    compliance_passed = None
    if note.rebalance:
        checks, compliance_passed = check_daily(note.rebalance,
                                                ctx.book or [])
        record = compliance_record_html(checks, compliance_passed)
        doc = ("compliance-record", "Compliance Record", "output",
               record, {"agent": "Compliance (rule engine)",
                        "stage": "Compliance",
                        "structured": {"checks": checks,
                                       "passed": compliance_passed}})
        all_docs.append(doc)
        if ctx.sink:
            ctx.sink.on_document(*doc)
        stages.append(["Compliance", "rule engine — no LLM", "—", 0,
                       "—", "—", "—", "$0.00"])
        if compliance_passed:
            instruction = DealingInstruction(
                legs=[InstructionLeg(
                    ticker=l.ticker, side=l.side,
                    size_pct_nav=l.size_pct_nav,
                    purpose="entry" if l.side == "buy"
                    else "funding_trim",
                    pacing=l.pacing) for l in note.rebalance],
                stops_to_place=[], standing_orders=[],
                validity="today", notes="daily rebalance")
            docs, calls, report = run_execution(ctx, llm, instruction)
            stages.append(_stage_row("Execution", "Trading Desk",
                                     ctx.quick_model, calls))
            all_calls += calls
            all_docs += docs

    tok_in = sum(c.usage.get("prompt_tokens", 0) for c in all_calls)
    tok_out = sum(c.usage.get("completion_tokens", 0)
                  for c in all_calls)
    reasoning = sum(
        (c.usage.get("completion_tokens_details") or {})
        .get("reasoning_tokens", 0) for c in all_calls)
    cost = sum(c.cost_usd for c in all_calls)
    elapsed = int(time.monotonic() - started)

    from collections import Counter
    tally = Counter()
    for d in all_docs:
        if d[0] == "position-verdicts":
            for v in d[4]["structured"]:
                tally[v["verdict"]] += 1
    verdict_bits = " · ".join(f"{n} {v.title()}"
                              for v, n in tally.most_common())
    if compliance_passed is False:
        tail = "rebalance FAILED compliance — returned"
    elif report is not None:
        tail = f"{len(report.fills)} fill(s)"
    elif note.rebalance:
        tail = "rebalance bound"
    else:
        tail = "no rebalance"
    outcome = (f"{n_pos} verdicts — {verdict_bits or 'none'} · {tail}"
               + (f" · {len(note.reunderwrite_triggers)} re-underwrite "
                  f"trigger(s)" if note.reunderwrite_triggers else ""))

    rollup = {
        "outcome": outcome,
        "calls": len(all_calls),
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "reasoning_tokens": reasoning,
        "cost_usd": round(cost, 4),
        "duration_seconds": elapsed,
        "stages": stages,
        "documents": [{"key": k, "title": t} for k, t, *_ in all_docs],
        "fills": ([f.model_dump() for f in report.fills]
                  if report is not None else []),
        "position_context": None,   # daily fills touch existing rows
    }
    if ctx.sink:
        ctx.sink.finalize(rollup)
    return rollup
