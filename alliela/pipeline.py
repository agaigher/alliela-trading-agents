"""Pipeline entry points. Coverage grows tier by tier — currently
Tiers 01–04 (Idea Generation → Selection Committee → Analyst team →
Thesis Desk). Each run returns a rollup the runner persists: per-stage
rows, totals, outcome, and the document list."""
import time

from alliela.stages.analysts import run_analysts
from alliela.stages.ideagen import run_ideagen
from alliela.stages.selection import run_selection
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

    tok_in = sum(c.usage.get("prompt_tokens", 0) for c in all_calls)
    tok_out = sum(c.usage.get("completion_tokens", 0) for c in all_calls)
    reasoning = sum(
        (c.usage.get("completion_tokens_details") or {})
        .get("reasoning_tokens", 0) for c in all_calls)
    cost = sum(c.cost_usd for c in all_calls)
    elapsed = int(time.monotonic() - started)

    prefix = f"“{ctx.tip}” → " if ctx.tip else "Free scan → "
    if thesis is not None:
        d = thesis.direction.lower()
        if "no position" in d or "pass" in d or "withdrawn" in d:
            outcome = (prefix + f"{thesis.ticker} judged — conviction "
                       f"withdrawn at the Thesis Desk "
                       f"({len(thesis.kill_criteria)} dated re-entry "
                       f"criteria) · {len(all_docs)} docs")
        else:
            outcome = (prefix + f"{thesis.ticker} thesis formed "
                       f"({thesis.direction.upper()}, "
                       f"{len(thesis.kill_criteria)} kill criteria) · "
                       f"tiers 05–09 not yet built · "
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
    }
    if ctx.sink:
        ctx.sink.finalize(rollup)
    return rollup
