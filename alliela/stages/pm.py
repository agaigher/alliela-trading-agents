"""Tier 07-08 — the Portfolio Manager column: three duties by the same
seat, on the PM model (Opus). PM - Decision reads the ORIGINAL
proposal (never risk's paraphrase) + the signed RiskConstraints + the
thesis + the book, and must address every constraint — satisfied or
explicitly escalated; an escalation triggers ONE bounce-back round
(Head of Risk responds, PM decides finally). PM - Funding makes room:
cash first, then trim lowest-conviction holdings. PM - Instruction
binds decision + funding into the Dealing Instruction — the handoff
document the Compliance gate checks at order release.

3 PM calls (+2 on a bounce). Documents: Portfolio Decision, Funding
Plan, Dealing Instruction."""
import json

from alliela.documents import (DealingInstruction, FundingPlan,
                               PortfolioDecision, RiskConstraints)
from alliela.structured import ask_validated

STAGE = "Portfolio Manager"


def run_pm(ctx, llm, thesis, proposal, constraints):
    """Returns (documents, calls, decision, funding, instruction).
    decision.action == 'decline' short-circuits funding/instruction."""
    calls = []
    book = json.dumps(ctx.book, indent=1, default=str) \
        if ctx.book else "(empty book)"
    base = (
        f"As-of date: {ctx.trade_date}.\n\n"
        f"The Transaction Proposal (the original — you read this, not "
        f"a paraphrase):\n{proposal.model_dump_json(indent=1)}\n\n"
        f"The signed RiskConstraints (binding):\n"
        f"{constraints.model_dump_json(indent=1)}\n\n"
        f"The Thesis:\n{thesis.model_dump_json(indent=1)}\n\n"
        f"The current book:\n{book}")

    decision_system = (
        "You are the Portfolio Manager of Alliela Fund 1 — "
        "PM - Decision, the accountable owner of the book. Decide: "
        "buy, sell, or decline. The RiskConstraints are binding: your "
        "compliance list must address EVERY constraint — 'satisfied' "
        "with how, or 'escalated' with why (an escalation goes back "
        "to the Head of Risk for one round; use it only when you "
        "genuinely believe a constraint is wrong for the book). "
        "Declining is a first-class outcome — the no-trade path costs "
        "nothing but the work already done. Size within the cap; "
        "conviction was earned upstream, not here. The mandate:\n\n"
        + ctx.mandate_text
        + "\n\nReturn STRICT JSON only, matching:\n"
        + json.dumps(PortfolioDecision.model_json_schema(), indent=1))

    decision = ask_validated(
        ctx, llm, agent="PM - Decision", stage=STAGE,
        system=decision_system, user=base,
        validate=PortfolioDecision.model_validate,
        schema_json=json.dumps(PortfolioDecision.model_json_schema()),
        model=ctx.pm_model, reasoning={"max_tokens": 2048},
        calls=calls)

    # One PM ↔ Head of Risk bounce-back round on escalation
    escalated = [c for c in decision.compliance
                 if c.status == "escalated"]
    if escalated:
        hr_system = (
            "You are the Head of Risk. The PM has escalated one or "
            "more of your signed constraints. Respond: for each "
            "escalation, either revise the constraint (with the new "
            "number and why) or hold firm (and why). Your response is "
            "final — there is exactly one bounce-back round. Return "
            "STRICT JSON: an updated RiskConstraints object, matching:"
            "\n" + json.dumps(RiskConstraints.model_json_schema(),
                              indent=1))
        hr_user = (base + "\n\nThe PM's decision with escalations:\n"
                   + decision.model_dump_json(indent=1))
        constraints = ask_validated(
            ctx, llm, agent="Head of Risk (bounce)", stage=STAGE,
            system=hr_system, user=hr_user,
            validate=RiskConstraints.model_validate,
            schema_json=json.dumps(
                RiskConstraints.model_json_schema()),
            model=ctx.deep_model, calls=calls)
        final_user = (
            f"The Head of Risk's final response to your escalation:\n"
            f"{constraints.model_dump_json(indent=1)}\n\n"
            f"Your prior decision:\n"
            f"{decision.model_dump_json(indent=1)}\n\n" + base +
            "\n\nMake your FINAL decision. The bounce round is over — "
            "every compliance item must now be 'satisfied' or the "
            "action must be 'decline'.")
        decision = ask_validated(
            ctx, llm, agent="PM - Decision (final)", stage=STAGE,
            system=decision_system, user=final_user,
            validate=PortfolioDecision.model_validate,
            schema_json=json.dumps(
                PortfolioDecision.model_json_schema()),
            model=ctx.pm_model, reasoning={"max_tokens": 2048},
            calls=calls)

    docs = [("portfolio", "Portfolio Decision", "output",
             decision.to_html("Portfolio Decision"),
             {"agent": "PM - Decision", "stage": STAGE,
              "structured": decision.model_dump()})]

    funding = None
    instruction = None
    if decision.action != "decline":
        funding_system = (
            "You are the Portfolio Manager on your second duty — "
            "PM - Funding: portfolio construction. Make room for the "
            "decided size from the real book: cash above the 1% floor "
            "first, then trim the LOWEST-conviction holdings — name "
            "them, justify each trim by conviction rank and thesis "
            "state, never trim winners to fund a maybe. Arithmetic "
            "must close: sources sum to the target; resulting cash "
            "respects the floor. The mandate:\n\n" + ctx.mandate_text
            + "\n\nReturn STRICT JSON only, matching:\n"
            + json.dumps(FundingPlan.model_json_schema(), indent=1))
        funding_user = (
            f"Decided size to fund: {decision.size_pct_nav:g}% NAV.\n\n"
            f"The current book:\n{book}\n\nCurrent cash: read it from "
            f"the book context if present; otherwise assume 1.65% "
            f"(floor 1.0%).")
        funding = ask_validated(
            ctx, llm, agent="PM - Funding", stage=STAGE,
            system=funding_system, user=funding_user,
            validate=FundingPlan.model_validate,
            schema_json=json.dumps(FundingPlan.model_json_schema()),
            model=ctx.pm_model, calls=calls)
        docs.append(("funding", "Funding Plan", "output",
                     funding.to_html("Funding Plan"),
                     {"agent": "PM - Funding", "stage": STAGE,
                      "structured": funding.model_dump()}))

        instr_system = (
            "You are the Portfolio Manager on your third duty — "
            "PM - Instruction. Bind the decision and the funding plan "
            "into the Dealing Instruction: every leg (entry tranches "
            "per the proposal's plan, funding trims, any hedge), "
            "sides, sizes, pacing; the stops the RiskConstraints "
            "mandate; standing orders; validity. This document goes "
            "to the Compliance gate and then the desk — it must be "
            "executable as written. Return STRICT JSON only, "
            "matching:\n"
            + json.dumps(DealingInstruction.model_json_schema(),
                         indent=1))
        instr_user = (
            f"The decision:\n{decision.model_dump_json(indent=1)}\n\n"
            f"The funding plan:\n{funding.model_dump_json(indent=1)}"
            f"\n\nThe proposal's entry plan:\n"
            f"{proposal.model_dump_json(indent=1)}\n\n"
            f"The RiskConstraints:\n"
            f"{constraints.model_dump_json(indent=1)}")
        instruction = ask_validated(
            ctx, llm, agent="PM - Instruction", stage=STAGE,
            system=instr_system, user=instr_user,
            validate=DealingInstruction.model_validate,
            schema_json=json.dumps(
                DealingInstruction.model_json_schema()),
            model=ctx.pm_model, calls=calls)
        docs.append(("instruction", "Dealing Instruction", "output",
                     instruction.to_html("Dealing Instruction"),
                     {"agent": "PM - Instruction", "stage": STAGE,
                      "structured": instruction.model_dump()}))

    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, decision, funding, instruction
