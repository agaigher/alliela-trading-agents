"""Intake: the owner's own text as the start of an origination step.

When a step starts from text rather than from a previous run, intake
turns it into what the step reads. Three moves, cheapest first:

1. Identify the ticker (one quick call), fetch the verified snapshot,
   and apply the platform listing check. An ineligible name ends the
   step here, before anything expensive runs.
2. Structured mode: one call converts the text into the typed
   documents the step needs. Anything the text does not give is filled
   with a SUGGESTED value, listed with its basis, never silently.
3. As-written mode: no conversion. The stages get the text verbatim
   (RawDoc) wherever they would have read a typed document.

The converted documents are also emitted under their standard keys
(chair, research-manager, trader, head-risk) so a later step can chain
from this run exactly as it would from a normal one.
"""
import json

from pydantic import BaseModel, Field

from alliela.documents import (IdeaBrief, RiskConstraints, Thesis,
                               TransactionProposal, _doc, _e)
from alliela.market import ticker_snapshot
from alliela.structured import ask_validated
from alliela.universe import listing_check

STAGE_TITLES = {"research": "Research Intake",
                "risk": "Risk Intake",
                "pm": "PM Intake"}
NODES = {"research": "intake-research",
         "risk": "intake-risk",
         "pm": "intake-pm"}


class RawDoc:
    """The owner's text standing in for a typed document, as written.

    Stages only ever serialise a handed-over document into their prompt
    (model_dump_json), so the verbatim text goes exactly where the typed
    JSON would have gone. Attribute reads fall back to None."""

    def __init__(self, text, label):
        self.text, self.label = text, label

    def model_dump_json(self, indent=None):
        return (f"[{self.label}: the fund owner's own text, used as "
                f"written — not a structured document]\n{self.text}")

    def model_dump(self):
        return {"raw_text": self.text}

    def __getattr__(self, name):
        return None


class TickerGuess(BaseModel):
    ticker: str = Field(description="The US ticker the text is about, "
                                    "e.g. 'MSFT'. Empty if none is named "
                                    "or clearly implied.")
    name: str = Field(description="Company name, '' if unknown")


class Suggestion(BaseModel):
    field: str = Field(description="Which field, e.g. 'proposal.stop'")
    value: str
    basis: str = Field(description="Why this value: the snapshot, the "
                                   "mandate, or a stated convention")


class ResearchIntake(BaseModel):
    brief: IdeaBrief
    suggested: list[Suggestion]


class RiskIntake(BaseModel):
    thesis: Thesis
    proposal: TransactionProposal
    suggested: list[Suggestion]


class PMIntake(BaseModel):
    thesis: Thesis
    proposal: TransactionProposal
    constraints: RiskConstraints
    suggested: list[Suggestion]


SCHEMAS = {"research": ResearchIntake, "risk": RiskIntake,
           "pm": PMIntake}
WHAT = {"research": "an Idea Brief for the Analyst team",
        "risk": "a Thesis and a Transaction Proposal for the Risk panel",
        "pm": "a Thesis, a Transaction Proposal and signed Risk "
              "Constraints for the Portfolio Manager"}


def intake_system_prompt(step):
    return (
        "You are the Intake desk. The fund owner has written their own "
        f"input, and the next stage needs {WHAT[step]}. Convert the "
        "owner's text into exactly those documents. Keep everything "
        "the owner says, in their terms. Where the text does not give "
        "a required field, fill it with a SUGGESTED value grounded in "
        "the verified snapshot or the mandate, and list every such "
        "field in `suggested` with its basis. Never present a "
        "suggestion as the owner's. Prices must be consistent with the "
        "verified snapshot. The platform is long only, US-listed "
        "stock: direction is always 'long' (a brief's direction "
        "'long'). The mandate binds:\n\n{mandate}\n\n"
        "Return STRICT JSON only, matching:\n"
        + json.dumps(SCHEMAS[step].model_json_schema(), indent=1))


def _ticker_system_prompt():
    return ("Identify the one US-listed stock this text is about. "
            "Return STRICT JSON only, matching:\n"
            + json.dumps(TickerGuess.model_json_schema()))


def _intake_html(step, text, ticker, snapshot, verdict, result=None):
    rows = ""
    if result is not None and result.suggested:
        rows = ("<h4>Suggested values (not the owner's)</h4><table>"
                "<thead><tr><th>Field</th><th>SUGGESTED</th><th>Basis"
                "</th></tr></thead><tbody>"
                + "".join(f"<tr><td>{_e(s.field)}</td><td>{_e(s.value)}"
                          f"</td><td>{_e(s.basis)}</td></tr>"
                          for s in result.suggested)
                + "</tbody></table>")
    mode = ("converted to the expected format" if result is not None
            else "used as written")
    return _doc(
        f"<h3>{_e(STAGE_TITLES[step])}</h3>"
        f"<h4>{_e(ticker or 'no ticker identified')} — {_e(verdict)}</h4>"
        f"<p><em>Owner's text, {mode}.</em></p>"
        f"<pre>{_e(text)}</pre>"
        + rows
        + (f"<p><strong>Verified snapshot.</strong> "
           f"{_e(json.dumps(snapshot)[:600])}</p>" if snapshot else ""))


def run_intake(ctx, llm, step, text, structured=True):
    """Returns (docs, calls, result) where result is None when the text
    cannot start the step, else a dict of the step's inputs:
    research → {brief}; risk → {thesis, proposal};
    pm → {thesis, proposal, constraints}."""
    calls, docs = [], []
    node, stage = NODES[step], STAGE_TITLES[step]
    agent = "Intake desk"

    guess = ask_validated(
        ctx, llm, agent=agent, stage=stage, node=node,
        override_prompt=False, system=_ticker_system_prompt(),
        user=text, validate=TickerGuess.model_validate,
        schema_json=json.dumps(TickerGuess.model_json_schema()),
        calls=calls)
    ticker = guess.ticker.strip().upper()
    snapshot = ticker_snapshot(ticker) if ticker else None
    ok, why = (listing_check(snapshot) if snapshot
               else (False, "no ticker named in the text"))

    def emit(*doc):
        docs.append(doc)
        if ctx.sink:
            ctx.sink.on_document(*doc)

    if not ok:
        emit("intake", stage, "output",
             _intake_html(step, text, ticker, snapshot,
                          f"cannot start: {why}"),
             {"agent": agent, "node": node, "stage": stage,
              "structured": {"ticker": ticker, "eligible": False,
                             "why": why}})
        return docs, calls, None

    if not structured:
        emit("intake", stage, "output",
             _intake_html(step, text, ticker, snapshot, "as written"),
             {"agent": agent, "node": node, "stage": stage,
              "raw": text,
              "structured": {"ticker": ticker, "name": guess.name,
                             "eligible": True, "mode": "raw"}})
        if step == "research":
            # The analysts need a ticker for their data packs; the rest
            # of the brief is the owner's text, verbatim.
            brief = IdeaBrief(
                viable=True, ticker=ticker, name=guess.name or ticker,
                direction="long", catalyst="(see the owner's text)",
                rationale=text,
                coverage_notes="Owner-supplied text, used as written.",
                ranked_rejects=[])
            return docs, calls, {"brief": brief}
        raw = RawDoc(text, "Owner's input")
        ref = RawDoc("(see the owner's text above)", "Owner's input")
        if step == "risk":
            return docs, calls, {"thesis": raw, "proposal": ref}
        return docs, calls, {"thesis": raw, "proposal": ref,
                             "constraints": ref}

    schema = SCHEMAS[step]
    system = intake_system_prompt(step).replace(
        "{mandate}", ctx.mandate_text)
    user = (f"As-of date: {ctx.trade_date}.\n\n"
            f"The owner's text:\n{text}\n\n"
            f"Verified market snapshot for {ticker} (real, fetched "
            f"now):\n{json.dumps(snapshot, indent=1)}")
    result = ask_validated(
        ctx, llm, agent=agent, stage=stage, node=node, system=system,
        user=user, validate=schema.model_validate,
        schema_json=json.dumps(schema.model_json_schema()), calls=calls)

    emit("intake", stage, "output",
         _intake_html(step, text, ticker, snapshot,
                      f"{len(result.suggested)} suggested value(s)",
                      result),
         {"agent": agent, "node": node, "stage": stage,
          "structured": {"ticker": ticker, "eligible": True,
                         "mode": "structured",
                         "suggested": [s.model_dump()
                                       for s in result.suggested]}})
    # Standard keys, so the next step can chain from this run.
    meta = {"agent": agent, "node": node, "stage": stage,
            "from_intake": True}
    out = {}
    if step == "research":
        brief = result.brief.model_copy(update={
            "ticker": ticker, "viable": True, "direction": "long"})
        emit("chair", "Idea Brief (from owner's text)", "output",
             brief.to_html("Idea Brief (from owner's text)"),
             {**meta, "structured": brief.model_dump()})
        out["brief"] = brief
    else:
        thesis = result.thesis.model_copy(update={"ticker": ticker})
        proposal = result.proposal.model_copy(update={"ticker": ticker})
        emit("research-manager", "Thesis (from owner's text)", "output",
             thesis.to_html("Thesis (from owner's text)"),
             {**meta, "structured": thesis.model_dump()})
        emit("trader", "Transaction Proposal (from owner's text)",
             "output",
             proposal.to_html("Transaction Proposal (from owner's text)"),
             {**meta, "structured": proposal.model_dump()})
        out.update(thesis=thesis, proposal=proposal)
        if step == "pm":
            constraints = result.constraints.model_copy(
                update={"ticker": ticker})
            emit("head-risk", "Risk Constraints (from owner's text)",
                 "output",
                 constraints.to_html("Risk Constraints (from owner's text)"),
                 {**meta, "structured": constraints.model_dump()})
            out["constraints"] = constraints
    return docs, calls, out
