"""The tool loop in ask_validated against a scripted fake model — no
network, no cost. Proves: tools execute and land on the call that
asked; the budget refuses the seventh call with a message; a tool the
agent was not given is refused; the evidence list gets every entry;
the final JSON still validates; call counts grow per round trip.

    python scripts/test_tool_loop.py
"""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alliela import tools as T                 # noqa: E402
from alliela.context import RunContext         # noqa: E402
from alliela.llm import CapturedCall           # noqa: E402
from alliela.structured import ask_validated   # noqa: E402


class FakeLLM:
    """Round 1: asks for two tools (one allowed, one not). Round 2:
    asks for six more (pushing past the budget of 6). Round 3: answers.
    """
    def __init__(self):
        self.round = 0
        self.seen_messages = []

    def call(self, *, model, messages, agent, stage, seq, tools=None,
             tool_choice=None, **kw):
        self.round += 1
        self.seen_messages.append(list(messages))
        cap = CapturedCall(agent=agent, stage=stage, seq=seq, model=model)
        cap.raw = {"fake": True}
        if self.round == 1:
            assert tools and any(t["function"]["name"] == "echo"
                                 for t in tools)
            cap.tool_calls = [
                {"id": "c1", "type": "function",
                 "function": {"name": "echo",
                              "arguments": json.dumps({"x": 1})}},
                {"id": "c2", "type": "function",
                 "function": {"name": "options_iv",
                              "arguments": json.dumps({"ticker": "ETN"})}},
            ]
        elif self.round == 2:
            cap.tool_calls = [
                {"id": f"c{i}", "type": "function",
                 "function": {"name": "echo",
                              "arguments": json.dumps({"x": i})}}
                for i in range(3, 10)]          # 7 asks, 5 fit
        else:
            assert tool_choice is None or self.round >= 8
            cap.text = json.dumps({"answer": "done"})
        return cap


calls_seen = []


class Sink:
    def on_call(self, cap):
        calls_seen.append(cap)

    def on_node(self, *a):
        pass


def main():
    # A fake tool registered for the test only.
    T.IMPL["echo"] = lambda x: {"status": "ok", "echo": x}
    T.SPECS["echo"] = T._spec("echo", "echo", {"x": {"type": "integer"}},
                              ["x"])
    ctx = RunContext(run_id="t", fund_id="t", flow_version="t",
                     engine_commit="t", mandate_text="m", tip="",
                     trade_date="2026-09-02", sink=Sink())
    llm = FakeLLM()
    evidence, calls = [], []
    result = ask_validated(
        ctx, llm, agent="Tester", stage="Test", system="s", user="u",
        validate=lambda d: d, schema_json="{}", calls=calls,
        node="market", tools=["echo"], tool_budget=6, evidence=evidence)

    assert result == {"answer": "done"}, result
    assert len(calls) == 3, [c.seq for c in calls]
    assert calls_seen == calls
    # Round 1: echo executed, options_iv refused as not-yours.
    r1 = calls[0].tools
    assert r1[0]["tool"] == "echo" and r1[0]["result"]["echo"] == 1
    assert r1[1]["result"]["status"] == "refused" and \
        "not one of your tools" in r1[1]["result"]["why"]
    # Round 2: five more executed (total 6), the last two refused on
    # budget with the message the analyst is meant to read.
    r2 = calls[1].tools
    statuses = [e["result"].get("status") for e in r2]
    assert statuses == ["ok"] * 5 + ["refused"] * 2, statuses
    assert "coverage_gaps" in r2[-1]["result"]["why"]
    # Evidence carries everything, in order, including refusals.
    assert len(evidence) == 9 and evidence[0] is r1[0]
    # The conversation the model saw in round 3 had the assistant turn
    # with tool_calls followed by one tool message per call.
    m3 = llm.seen_messages[2]
    assert m3[2]["role"] == "assistant" and len(m3[2]["tool_calls"]) == 2
    assert [m["role"] for m in m3[3:5]] == ["tool", "tool"]
    assert m3[3]["tool_call_id"] == "c1"
    print("tool loop: ok —", len(calls), "calls,", len(evidence),
          "evidence entries, budget enforced at 6")


if __name__ == "__main__":
    main()
