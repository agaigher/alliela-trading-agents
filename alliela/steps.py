"""Origination as four independent steps, each its own run.

  ideas    → Idea Generation, Selection             hands on: brief
  research → [intake] Analysts, Thesis, Structuring hands on: thesis, proposal
  risk     → [intake] Risk Panel                     hands on: constraints
  pm       → [intake] PM, Compliance, Execution      ends in fills

A step reads its inputs from `inputs` (typed documents the runner
rebuilt from an earlier run's archive; see `inputs_from_docs`) or from
the owner's `text` through the intake desk. It stops at its own
boundary. `rollup["continue"]` says whether the next step has anything
to work on, which is what "Run all" chains on.

The stage functions are reused unchanged; `run_origination` in
pipeline.py stays as the legacy one-shot path.
"""
import time

from alliela.compliance import check_instruction
from alliela.documents import (IdeaBrief, RiskConstraints, Thesis,
                               TransactionProposal,
                               compliance_record_html)
from alliela.pipeline import _fmt_tokens, _stage_row  # noqa: F401
from alliela.stages.analysts import run_analysts
from alliela.stages.execution import run_execution
from alliela.stages.ideagen import run_ideagen
from alliela.stages.intake import RawDoc, run_intake
from alliela.stages.pm import run_pm
from alliela.stages.risk import run_risk
from alliela.stages.selection import run_selection
from alliela.stages.structuring import run_structuring
from alliela.stages.thesis import run_thesis
from alliela.structured import note_node

STEPS = ("ideas", "research", "risk", "pm")
RUN_TYPES = {s: f"orig_{s}" for s in STEPS}
STEP_OF = {v: k for k, v in RUN_TYPES.items()}

# What each step needs, by the document key that carries it.
NEEDS = {"research": {"brief": "chair"},
         "risk": {"thesis": "research-manager", "proposal": "trader"},
         "pm": {"thesis": "research-manager", "proposal": "trader",
                "constraints": "head-risk"}}
MODELS = {"brief": IdeaBrief, "thesis": Thesis,
          "proposal": TransactionProposal, "constraints": RiskConstraints}


def inputs_from_docs(step, docs):
    """Rebuild a step's typed inputs from archived documents.

    `docs` is the runner's list of (key, meta) from the source run and
    its ancestors, nearest first. A typed payload wins; an owner's
    as-written text (an intake doc carrying `raw`) stands in for any
    document it preceded. Raises ValueError naming what is missing."""
    out, raw = {}, None
    for key, meta in docs:
        meta = meta or {}
        if raw is None and key == "intake" and meta.get("raw"):
            raw = meta["raw"]
        for name, doc_key in NEEDS[step].items():
            if name in out or key != doc_key:
                continue
            payload = meta.get("structured")
            if payload:
                out[name] = MODELS[name].model_validate(payload)
    missing = [n for n in NEEDS[step] if n not in out]
    if missing and raw is not None:
        for n in missing:
            out[n] = RawDoc(raw if n == "thesis"
                            else "(see the owner's text above)",
                            "Owner's input")
        missing = []
    if missing:
        raise ValueError(f"the source run has no {', '.join(missing)} "
                         f"to start the {step} step from")
    return out


def _totals(all_calls):
    tok_in = sum(c.usage.get("prompt_tokens", 0) for c in all_calls)
    tok_out = sum(c.usage.get("completion_tokens", 0) for c in all_calls)
    reasoning = sum(
        (c.usage.get("completion_tokens_details") or {})
        .get("reasoning_tokens", 0) for c in all_calls)
    return tok_in, tok_out, reasoning, sum(c.cost_usd for c in all_calls)


def run_step(ctx, llm, step, inputs=None, text=None, structured=True):
    """Run one origination step. Returns the rollup (streamed to
    ctx.sink like every other flow), plus `continue` and `ticker`."""
    if step not in STEPS:
        raise ValueError(f"unknown step {step!r}")
    started = time.monotonic()
    stages, all_calls, all_docs = [], [], []
    inputs = dict(inputs or {})
    fills, pos_ctx, cont, ticker = [], None, False, None

    def add(name, agents, model, docs, calls):
        stages.append(_stage_row(name, agents, model, calls))
        all_calls.extend(calls)
        all_docs.extend(docs)

    if step != "ideas" and text:
        docs, calls, got = run_intake(ctx, llm, step, text, structured)
        add("Intake", "Intake desk", ctx.quick_model, docs, calls)
        if got is None:
            why = docs[-1][4]["structured"].get("why", "")
            return _finish(ctx, started, stages, all_calls, all_docs,
                           f"Intake stopped: {why}", False, None)
        inputs.update(got)

    if step == "ideas":
        docs, calls, combined = run_ideagen(ctx, llm)
        add("Idea Generation", "3 desks + Head", ctx.quick_model,
            docs, calls)
        docs, calls, brief = run_selection(ctx, llm, combined)
        add("Selection Committee", "3 scorers + Chair", ctx.quick_model,
            docs, calls)
        ticker = brief.ticker if brief.viable else None
        cont = bool(brief.viable)
        outcome = (f"{brief.ticker} selected ({len(combined.candidates)} "
                   f"scored)" if brief.viable else
                   "no candidate survived Selection")

    elif step == "research":
        brief = inputs["brief"]
        ticker = brief.ticker
        docs, calls, reports = run_analysts(ctx, llm, brief)
        add("Analyst Team", "4 analysts + Lead", ctx.quick_model,
            docs, calls)
        docs, calls, thesis = run_thesis(ctx, llm, brief, reports)
        add("Thesis Desk", "Bull · Bear ×3 + Mgr + Pre-mortem",
            ctx.deep_model, docs, calls)
        if thesis.direction == "pass":
            outcome = (f"{thesis.ticker} — PASS at the Thesis Desk "
                       f"({len(thesis.kill_criteria)} dated re-entry "
                       f"criteria)")
        else:
            docs, calls, proposal = run_structuring(ctx, llm, thesis,
                                                    reports)
            add("Pre-Trade Structuring", "Trading Desk", ctx.deep_model,
                docs, calls)
            cont = True
            outcome = (f"{thesis.ticker} LONG — "
                       f"{proposal.size_pct_nav:g}% NAV proposed")

    elif step == "risk":
        thesis, proposal = inputs["thesis"], inputs["proposal"]
        ticker = getattr(thesis, "ticker", None) or \
            getattr(proposal, "ticker", None)
        docs, calls, constraints = run_risk(ctx, llm, thesis, proposal)
        add("Risk Panel", "3 lenses + Head of Risk", ctx.deep_model,
            docs, calls)
        ticker = ticker or constraints.ticker
        if constraints.veto:
            outcome = f"{ticker} VETOED by the Head of Risk"
        else:
            cont = True
            outcome = (f"{ticker} — Risk Constraints signed (cap "
                       f"{constraints.max_position_pct_nav:g}% NAV)")

    else:  # pm
        thesis = inputs["thesis"]
        proposal = inputs["proposal"]
        constraints = inputs["constraints"]
        docs, calls, decision, funding, instruction = run_pm(
            ctx, llm, thesis, proposal, constraints)
        add("Portfolio Manager", "Decision · Funding · Instruction",
            ctx.pm_model, docs, calls)
        ticker = (getattr(thesis, "ticker", None)
                  or (instruction.legs[0].ticker
                      if instruction and instruction.legs else None))
        if instruction is None:
            outcome = (f"{ticker or 'the name'} — PM DECLINED "
                       f"(no-trade, first-class outcome)")
        else:
            # Typed constraints bind; an owner's as-written text cannot
            # be checked mechanically, so those rules report N/E.
            typed = constraints if isinstance(constraints,
                                              RiskConstraints) else None
            note_node(ctx, "compliance", "Compliance",
                      "Compliance (rule engine)", "running")
            checks, passed = check_instruction(
                instruction, decision, typed, ctx.book, funding,
                restrictions=ctx.restrictions)
            note_node(ctx, "compliance", "Compliance",
                      "Compliance (rule engine)", "done")
            doc = ("compliance-record", "Compliance Record", "output",
                   compliance_record_html(checks, passed),
                   {"agent": "Compliance (rule engine)",
                    "node": "compliance", "stage": "Compliance",
                    "structured": {"checks": checks, "passed": passed}})
            all_docs.append(doc)
            if ctx.sink:
                ctx.sink.on_document(*doc)
            stages.append(["Compliance", "rule engine — no LLM", "—", 0,
                           "—", "—", "—", "$0.00"])
            if not passed:
                outcome = (f"{ticker} — Compliance FAILED the Dealing "
                           f"Instruction; decision returned")
            else:
                docs, calls, report = run_execution(ctx, llm,
                                                    instruction)
                add("Execution", "Trading Desk", ctx.quick_model,
                    docs, calls)
                fills = [f.model_dump() for f in report.fills]
                filled = sum(f.size_pct_nav for f in report.fills
                             if f.purpose == "entry")
                outcome = (f"{ticker} {decision.action.upper()} "
                           f"{decision.size_pct_nav:g}% NAV · "
                           f"{filled:g}% filled")
                kills = getattr(thesis, "kill_criteria", None) or []
                stops = (constraints.mandatory_stops
                         if typed is not None else [])
                pos_ctx = {
                    "ticker": ticker,
                    "name": getattr(thesis, "name", None) or ticker,
                    "direction": "L",  # long only (universe.py)
                    "stop": stops[0] if stops else "",
                    "target": getattr(thesis, "target_price", None),
                    "kill_note": (f"0 fired · next {kills[0].date}"
                                  if kills else ""),
                }

    return _finish(ctx, started, stages, all_calls, all_docs, outcome,
                   cont, ticker, fills, pos_ctx)


def _finish(ctx, started, stages, all_calls, all_docs, outcome, cont,
            ticker, fills=(), pos_ctx=None):
    tok_in, tok_out, reasoning, cost = _totals(all_calls)
    prefix = f"“{ctx.tip}” → " if ctx.tip else ""
    rollup = {
        "outcome": f"{prefix}{outcome} · {len(all_docs)} docs",
        "calls": len(all_calls),
        "tokens_in": tok_in,
        "tokens_out": tok_out,
        "reasoning_tokens": reasoning,
        "cost_usd": round(cost, 4),
        "duration_seconds": int(time.monotonic() - started),
        "stages": stages,
        "documents": [{"key": k, "title": t} for k, t, *_ in all_docs],
        "fills": list(fills),
        "position_context": pos_ctx if fills else None,
        "continue": cont,
        "ticker": ticker,
    }
    if ctx.sink:
        ctx.sink.finalize(rollup)
    return rollup
