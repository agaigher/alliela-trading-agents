"""Tier 05 — Pre-Trade Structuring (Trading Desk duty #1). One
deep-think call that turns the Thesis into a concrete Transaction
Proposal: tranched entry with limits, participation vs the verified
ADV, hard stop, standing orders, the borrow-realism check (mandatory
for shorts — no fantasy shorts on a paper book), costs, timeline, and
the questions Risk should stress first. The proposal forks downstream:
to the Risk panel for stress-testing AND directly to the PM.

Runs only when the Thesis direction is long or short — a pass ends the
run at the desk."""
import json

from alliela.documents import TransactionProposal
from alliela.market import ticker_snapshot
from alliela.structured import ask_validated

STAGE = "Pre-Trade Structuring"


def run_structuring(ctx, llm, thesis, reports):
    """Returns (documents, calls, proposal)."""
    calls = []
    snapshot = ticker_snapshot(thesis.ticker)
    positioning = reports["sentiment"].model_dump()

    system = (
        "You are the Trading Desk of Alliela Fund 1, on your first "
        "duty: Pre-Trade Structuring. Turn the Thesis into a concrete, "
        "executable Transaction Proposal. Rules: size within the "
        "mandate's limits and justify the number; tranche the entry "
        "with explicit triggers and limit discipline; participation "
        "must cite the VERIFIED average daily value traded from the "
        "snapshot, never a guessed one; the stop must be a level with "
        "a basis, consistent with the Thesis's kill criteria; the "
        "borrow-realism check is mandatory — for a short, borrowable "
        "at size per the Positioning report with borrow cost charged "
        "against expected P&L; for a long, mark it 'n/a — long' with "
        "a one-line for-the-record note. Be honest about costs. The "
        "mandate binds:\n\n" + ctx.mandate_text
        + "\n\nReturn STRICT JSON only, matching:\n"
        + json.dumps(TransactionProposal.model_json_schema(),
                     indent=1))
    user = (
        f"As-of date: {ctx.trade_date}.\n\n"
        f"The Thesis:\n{thesis.model_dump_json(indent=1)}\n\n"
        f"Verified market snapshot (real, fetched now):\n"
        f"{json.dumps(snapshot, indent=1)}\n\n"
        f"The Positioning report (borrow/ownership evidence):\n"
        f"{json.dumps(positioning, indent=1)}")

    proposal = ask_validated(
        ctx, llm, agent="Trading Desk", stage=STAGE,
        system=system, user=user,
        validate=TransactionProposal.model_validate,
        schema_json=json.dumps(TransactionProposal.model_json_schema()),
        model=ctx.deep_model, calls=calls)

    docs = [("trader", "Transaction Proposal", "output",
             proposal.to_html("Transaction Proposal"),
             {"agent": "Trading Desk", "stage": STAGE,
              "structured": proposal.model_dump(),
              "verified_snapshot": snapshot})]
    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, proposal
