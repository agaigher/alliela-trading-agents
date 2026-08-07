"""Pipeline entry points. Coverage grows tier by tier — currently
Tier 01 (Idea Generation). Each run returns a rollup the runner
persists: per-stage rows, totals, outcome, and the document list."""
import time

from alliela.stages.ideagen import run_ideagen


def _fmt_tokens(n):
    if n >= 1000:
        return f"{n / 1000:.1f}K".replace(".0K", "K")
    return str(n)


def run_origination(ctx, llm):
    """Execute the origination pipeline (tier 01 for now). Returns the
    rollup dict; calls and documents stream to ctx.sink as they
    happen."""
    started = time.monotonic()
    docs, calls, combined = run_ideagen(ctx, llm)

    tok_in = sum(c.usage.get("prompt_tokens", 0) for c in calls)
    tok_out = sum(c.usage.get("completion_tokens", 0) for c in calls)
    reasoning = sum(
        (c.usage.get("completion_tokens_details") or {})
        .get("reasoning_tokens", 0) for c in calls)
    cost = sum(c.cost_usd for c in calls)
    elapsed = int(time.monotonic() - started)

    n = len(combined.candidates)
    outcome = (f"“{ctx.tip}” → " if ctx.tip else "Free scan → ") + \
        (f"{n} candidates compiled · Idea Generation only "
         f"(tiers 02–09 not yet built) · {len(docs)} docs")

    rollup = {
        "outcome": outcome,
        "calls": len(calls),
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "reasoning_tokens": reasoning,
        "cost_usd": round(cost, 4),
        "duration_seconds": elapsed,
        "stages": [[
            "Idea Generation", "3 desks + Head",
            ctx.quick_model.split("/")[-1], len(calls),
            _fmt_tokens(tok_in), _fmt_tokens(tok_out),
            _fmt_tokens(reasoning) if reasoning else "—",
            f"${cost:.2f}",
        ]],
        "documents": [{"key": k, "title": t} for k, t, *_ in docs],
    }
    if ctx.sink:
        ctx.sink.finalize(rollup)
    return rollup
