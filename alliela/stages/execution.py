"""Tier 09 — Execution (Trading Desk duty #2). Turns the
compliance-released Dealing Instruction into paper fills at real
marks: the fill prices come from a fresh verified snapshot, the LLM
writes the report and the pacing judgment. One quick-think call.
The fills are the only thing that ever writes to the PMS — and the
write itself happens in the runner (worker), never in the engine."""
import json

from alliela.documents import ExecutionReport
from alliela.market import ticker_snapshot
from alliela.structured import ask_validated

STAGE = "Execution"


def run_execution(ctx, llm, instruction):
    """Returns (documents, calls, report)."""
    calls = []
    tickers = sorted({l.ticker for l in instruction.legs})
    snapshots = {t: ticker_snapshot(t) for t in tickers}

    system = (
        "You are the Trading Desk of Alliela Fund 1 on your second "
        "duty: Execution, on a closed paper book marked against real "
        "prices. Execute the Dealing Instruction: day-1 fills happen "
        "at the verified snapshot price (this is the paper book's "
        "mark — never invent a price), with an honest slippage note "
        "sized from the leg vs the verified ADV. Legs whose pacing "
        "defers them (resting tranches, GTC orders, multi-day trims) "
        "go to 'unfilled' with the reason — do NOT fill a leg the "
        "instruction paces beyond today. List every stop you placed. "
        "Return STRICT JSON only, matching:\n"
        + json.dumps(ExecutionReport.model_json_schema(), indent=1))
    user = (
        f"As-of date: {ctx.trade_date}.\n\n"
        f"The Dealing Instruction (compliance-released):\n"
        f"{instruction.model_dump_json(indent=1)}\n\n"
        f"Verified snapshots (real prices, fetched now):\n"
        f"{json.dumps(snapshots, indent=1)}")

    report = ask_validated(
        ctx, llm, agent="Execution", stage=STAGE,
        system=system, user=user,
        validate=ExecutionReport.model_validate,
        schema_json=json.dumps(ExecutionReport.model_json_schema()),
        calls=calls)

    docs = [("execution", "Execution Report", "output",
             report.to_html("Execution Report"),
             {"agent": "Execution", "stage": STAGE,
              "structured": report.model_dump(),
              "snapshots": snapshots})]
    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, report
