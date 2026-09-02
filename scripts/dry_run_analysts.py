"""Tier 03 alone, locally, against a hand-written brief — the dry run
for the analysts' tools (Phase A exit check before a paid run).

Runs the four specialists + Lead + revision pass with the free tools
enabled, writes calls/documents/evidence to runs/<id>/ via FileSink,
and prints the tool trail. Quick model only: ~$0.15–0.30 on the house
OpenRouter key, no fund credits.

    python scripts/dry_run_analysts.py [TICKER] [NAME]

OPENROUTER_API_KEY comes from the environment or the repo root .env.
"""
import json
import os
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alliela.context import RunContext            # noqa: E402
from alliela.documents import IdeaBrief           # noqa: E402
from alliela.llm import OpenRouter                # noqa: E402
from alliela.sinks import FileSink                # noqa: E402
from alliela.stages.analysts import run_analysts  # noqa: E402


def _key():
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    env = ROOT.parent / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    raise SystemExit("OPENROUTER_API_KEY not set and not in ../.env")


MANDATE = """Global Equities Tactical Fund — paper mandate (dry run).
Universe: listed equities, developed markets. Single-name cap 8% NAV.
Long/short. Benchmark MSCI World. Base currency USD.
Every position must carry dated, decidable kill criteria."""


def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "ETN"
    name = sys.argv[2] if len(sys.argv) > 2 else "Eaton Corporation plc"
    run_id = f"local-analysts-{time.strftime('%Y%m%d-%H%M%S')}"
    brief = IdeaBrief(
        viable=True, ticker=ticker, name=name, direction="long",
        catalyst=("US grid-security executive order (26 Aug 2026) and "
                  "Siemens Energy's US grid exit (28 Aug 2026) "
                  "reallocating grid-equipment demand; Q4 2026 "
                  "earnings as the confirming print"),
        rationale=("Electrical Americas backlog and margin trajectory "
                   "are the thesis; the market has re-rated on the "
                   "narrative before the segment numbers confirmed it"),
        coverage_notes=("Verify from filings: Electrical Americas "
                        "segment revenue, operating margin and backlog "
                        "trend over the last 6 quarters; total debt "
                        "and D/E; any 8-K since 26 Aug. Get realized "
                        "and implied vol for sizing."),
        ranked_rejects=[])
    ctx = RunContext(
        run_id=run_id, fund_id="local", flow_version="dev",
        engine_commit="dev", mandate_text=MANDATE, tip="",
        trade_date=time.strftime("%Y-%m-%d"),
        sink=FileSink(root=str(ROOT / "runs"), run_id=run_id),
        fund_name="Global Equities Tactical Fund (dry run)")
    llm = OpenRouter(api_key=_key())

    started = time.monotonic()
    docs, calls, reports = run_analysts(ctx, llm, brief)
    elapsed = int(time.monotonic() - started)

    cost = sum(c.cost_usd for c in calls)
    tool_calls = [(c.agent, e) for c in calls for e in c.tools]
    print(f"\n{run_id}: {len(calls)} calls, ${cost:.3f}, {elapsed}s, "
          f"{len(docs)} documents, {len(tool_calls)} tool calls")
    for agent, e in tool_calls:
        res = e["result"]
        status = res.get("status", "ok") if isinstance(res, dict) else "ok"
        args = json.dumps(e["args"], ensure_ascii=False)[:90]
        print(f"  {agent:22} {e['tool']:20} {status:14} {e['ms']:>6}ms "
              f"{args}")
    print("\nCoverage gaps after revision:")
    for key, rep in reports.items():
        for g in rep.coverage_gaps:
            print(f"  [{key}] {g[:140]}")
    print(f"\ndocuments → {ROOT / 'runs' / run_id}")
    ctx.sink.finalize({"calls": len(calls), "cost_usd": cost,
                       "tool_calls": len(tool_calls)})


if __name__ == "__main__":
    main()
