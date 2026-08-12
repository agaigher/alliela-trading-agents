"""Pipeline entry points. Coverage grows tier by tier — currently
Tiers 01–02 (Idea Generation → Selection Committee). Each run returns
a rollup the runner persists: per-stage rows, totals, outcome, and the
document list."""
import time

from alliela.stages.ideagen import run_ideagen
from alliela.stages.selection import run_selection


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

    tok_in = sum(c.usage.get("prompt_tokens", 0) for c in all_calls)
    tok_out = sum(c.usage.get("completion_tokens", 0) for c in all_calls)
    reasoning = sum(
        (c.usage.get("completion_tokens_details") or {})
        .get("reasoning_tokens", 0) for c in all_calls)
    cost = sum(c.cost_usd for c in all_calls)
    elapsed = int(time.monotonic() - started)

    prefix = f"“{ctx.tip}” → " if ctx.tip else "Free scan → "
    if brief.viable:
        outcome = (prefix + f"{brief.ticker} selected at Committee "
                   f"({len(combined.candidates)} scored) · tiers 03–09 "
                   f"not yet built · {len(all_docs)} docs")
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
