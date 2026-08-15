"""Tier 06 — Risk panel. Three functional lenses examine the
Transaction Proposal against the live book in a sequential debate
(each lens sees and responds to the prior views), then the Head of
Risk reads the debate against the book and signs the typed
RiskConstraints — binding on the PM. 4 LLM calls, all deep-think;
the Head runs with extended reasoning.

Risk has teeth: a veto is available, stops are mandatory not
advisory, and the constraints may be far tighter than the mandate.

Documents held to the sample formats: Liquidity / Concentration /
Drawdown View, Risk Debate Transcript, Risk Constraints."""
import json

from alliela.documents import (RiskConstraints, RiskView,
                               transcript_html)
from alliela.structured import ask_validated

STAGE = "Risk Panel"

LENSES = [
    ("liquidity", "Liquidity Risk",
     "exit capacity: how fast can the fund get OUT at size, in stress, "
     "when everyone else is exiting too? Judge entry pacing vs the "
     "verified ADV, exit horizon at stressed participation, and what "
     "gaps or halts would do. For a short, remember the exit is a "
     "BUY-BACK — liquidity risk is squeeze risk."),
    ("concentration", "Concentration Risk",
     "stacking against the book: what does this position add to "
     "exposures the fund already carries — country, sector, factor, "
     "theme? Judge gross AND net. Name the overlapping positions from "
     "the book explicitly and quantify the stacked exposure."),
    ("drawdown", "Drawdown Risk",
     "loss under stress: what does the book's P&L look like if this "
     "thesis is wrong, the stop gaps, or the catalyst breaks the wrong "
     "way? Size the plausible worst case in NAV terms. For a short, "
     "the loss is unbounded — stress days-to-cover and squeeze "
     "dynamics."),
]

TITLES = {"liquidity": "Liquidity View",
          "concentration": "Concentration View",
          "drawdown": "Drawdown View"}


def run_risk(ctx, llm, thesis, proposal):
    """Returns (documents, calls, constraints)."""
    calls = []
    book = json.dumps(ctx.book, indent=1, default=str) \
        if ctx.book else "(empty book)"
    base_context = (
        f"As-of date: {ctx.trade_date}.\n\n"
        f"The Transaction Proposal:\n"
        f"{proposal.model_dump_json(indent=1)}\n\n"
        f"The Thesis (kill criteria included):\n"
        f"{thesis.model_dump_json(indent=1)}\n\n"
        f"The current book (real portfolio state):\n{book}")

    views = {}
    turns = []
    for key, lens_name, lens_rules in LENSES:
        system = (
            f"You are the {lens_name} lens on Alliela Fund 1's Risk "
            f"panel. Your lens, and only your lens: {lens_rules}\n\n"
            "This is a debate: read the prior lenses' views and "
            "respond where you disagree or where their concerns "
            "compound yours. Recommend concrete, typed constraints — "
            "numbers, not sentiment. The mandate's limits are the "
            "outer bound; you may be far tighter:\n\n"
            + ctx.mandate_text
            + "\n\nReturn STRICT JSON only, matching:\n"
            + json.dumps(RiskView.model_json_schema(), indent=1))
        prior = "\n\n".join(
            f"## {TITLES[k]}\n{views[k].model_dump_json(indent=1)}"
            for k in views) or "(you open the panel)"
        user = base_context + f"\n\nPrior lens views:\n\n{prior}"
        views[key] = ask_validated(
            ctx, llm, agent=lens_name, stage=STAGE, system=system,
            user=user, validate=RiskView.model_validate,
            schema_json=json.dumps(RiskView.model_json_schema()),
            model=ctx.deep_model, calls=calls)
        turns.append((lens_name, views[key].assessment))

    head_system = (
        "You are the Head of Risk of Alliela Fund 1 — the independent "
        "risk authority. Read the three lens views against the book "
        "and sign the RiskConstraints: binding on the Portfolio "
        "Manager, who must satisfy each constraint or explicitly "
        "escalate. Aggregate by judgment — where lenses conflict, "
        "decide; where they compound, tighten. Stops are mandatory, "
        "not advisory. Use the veto only when no constraint set makes "
        "the trade acceptable. Every number in your constraints must "
        "trace to a lens view, the book, or the mandate. Return "
        "STRICT JSON only, matching:\n"
        + json.dumps(RiskConstraints.model_json_schema(), indent=1))
    head_user = base_context + "\n\nThe three lens views:\n\n" + \
        "\n\n".join(f"## {TITLES[k]}\n"
                    f"{views[k].model_dump_json(indent=1)}"
                    for k, _, _ in LENSES)
    constraints = ask_validated(
        ctx, llm, agent="Head of Risk", stage=STAGE,
        system=head_system, user=head_user,
        validate=RiskConstraints.model_validate,
        schema_json=json.dumps(RiskConstraints.model_json_schema()),
        model=ctx.deep_model, reasoning={"max_tokens": 2048},
        calls=calls)

    docs = []
    for key, lens_name, _ in LENSES:
        docs.append((key, TITLES[key], "output",
                     views[key].to_html(TITLES[key]),
                     {"agent": lens_name, "stage": STAGE,
                      "structured": views[key].model_dump()}))
    docs.append(("risk-debate", "Risk Debate Transcript", "transcript",
                 transcript_html("Risk Panel — Debate Transcript",
                                 turns),
                 {"agent": "Risk Panel", "stage": STAGE}))
    docs.append(("head-risk", "Risk Constraints", "output",
                 constraints.to_html("Risk Constraints"),
                 {"agent": "Head of Risk", "stage": STAGE,
                  "structured": constraints.model_dump()}))
    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, constraints
