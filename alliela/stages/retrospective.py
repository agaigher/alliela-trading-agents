"""The Retrospective flow — the weekly meta-loop. Performance review
judges the PROCESS, not the P&L: it has no trading authority, writes
into no live flow, and its output is a ranked Improvement Backlog the
Developer Agent (a coding agent outside the run loop) implements as a
reviewed commit — the next flow version.

Six calls: Scorekeeper → Attribution (post-decision reality from real
price/news packs) → three Process Auditors (Prompt / Structure /
Tooling — reading the ACTUAL prompts from the code and the archived
outputs/reasoning from the run ledger, injected via
ctx.review_pack) → Head of Performance Review (the flow's only
deep-think call).

Inputs come from ctx.review_pack, assembled by the runner:
  runs:            [{id, run_type, outcome, cost, time, flow_version}]
  theses:          [{run_id, structured thesis, premortem_most_likely}]
  manager_traces:  [{run_id, output_excerpt, reasoning_excerpt}]
  judged_tickers:  [{ticker, name, decided_on, decision}]
"""
import json

from alliela.documents import (AttributionReport, AuditFinding,
                               HeadReviewOutput, WeeklyScoreboard)
from alliela.market import context_pack, price_pack
from alliela.stages.thesis import ROUNDS, manager_system_prompt
from alliela.structured import ask_validated

STAGE = "Retrospective"

AUDITORS = [
    ("prompt-audit", "Prompt Auditor",
     "was the failure/pattern absent from the agent's INSTRUCTIONS? "
     "You are given the actual system prompt the Research Manager "
     "runs on, verbatim from the code, plus its archived outputs and "
     "reasoning. Propose the minimal prompt diff — quote the exact "
     "lines you would change and the replacement text."),
    ("structure-audit", "Structure Auditor",
     "would a different STRUCTURE have caught it — an extra node, a "
     "different debate shape, another revision round? You are given "
     "the pipeline's actual structure. Note especially: order effects "
     "(who speaks last), missing cross-checks, stages that cannot "
     "push back."),
    ("tooling-audit", "Tooling Auditor",
     "would a TOOL or data source the pipeline lacks have changed the "
     "input set? Cost every proposal honestly against false-positive "
     "noise and added latency — a tool that helps once and distracts "
     "weekly is a bad trade."),
]

TITLES = {"prompt-audit": "Prompt Audit",
          "structure-audit": "Structure Audit",
          "tooling-audit": "Tooling Audit"}


def _structure_description():
    return (
        f"Origination structure (code facts): 01 three idea desks + "
        f"Head (1 revision round) → 02 three scoring lenses + Chair "
        f"(any fatal eliminates) → 03 four analysts + Lead (1 revision "
        f"round; pack-only citation rule) → 04 Thesis Desk: Bull/Bear "
        f"alternating for {ROUNDS} rounds ({ROUNDS * 2} turns, Bull "
        f"opens, BEAR ALWAYS CLOSES) → Research Manager judges "
        f"(long/short/pass) → Pre-mortem → 05 Structuring (skipped on "
        f"pass) → 06 Risk panel (3 lenses sequential + Head of Risk) "
        f"→ 07 PM Decision/Funding/Instruction (one bounce round) → "
        f"08 deterministic Compliance gate → 09 Execution. A pass at "
        f"the Thesis Desk ends the run — no downstream stage can "
        f"challenge a pass.")


def run_retrospective(ctx, llm):
    """Returns (documents, calls, head_output)."""
    calls, docs = [], []
    pack = ctx.review_pack or {}
    runs = pack.get("runs", [])
    theses = pack.get("theses", [])
    traces = pack.get("manager_traces", [])
    judged = pack.get("judged_tickers", [])

    # real post-decision reality: price action + news for judged names
    reality = {j["ticker"]: price_pack(j["ticker"]) for j in judged}
    news = context_pack([f"{j['name']} stock" for j in judged],
                        per_query=6)

    def ask(agent, system, user, schema_cls, model=None,
            reasoning=None):
        return ask_validated(
            ctx, llm, agent=agent, stage=STAGE, system=system,
            user=user, validate=schema_cls.model_validate,
            schema_json=json.dumps(schema_cls.model_json_schema()),
            model=model, reasoning=reasoning, calls=calls)

    base = (
        f"As-of date: {ctx.trade_date}.\n\n"
        f"The period's runs:\n{json.dumps(runs, indent=1, default=str)}"
        f"\n\nTheses produced (structured, incl. stance and kill "
        f"criteria):\n{json.dumps(theses, indent=1, default=str)}\n\n"
        f"The book:\n"
        f"{json.dumps(ctx.book, indent=1, default=str)}")

    # 1 — Scorekeeper
    scoreboard = ask(
        "Scorekeeper",
        "You are the Scorekeeper of Alliela Fund 1's weekly "
        "Retrospective. Score the fund against reality: classify "
        "positions Worked / Failed / Inconclusive RELATIVE TO THEIR "
        "THESIS EXPECTATION, never raw P&L — and be honest about data "
        "status (seeded mock positions are labelled as such, and "
        "no_position is a real classification when the fund made no "
        "trade). Your run_summary must name patterns across runs, not "
        "just list them. Decide the forensics scope: what deserves "
        "full attribution this week. Return STRICT JSON matching:\n"
        + json.dumps(WeeklyScoreboard.model_json_schema(), indent=1),
        base, WeeklyScoreboard)
    docs.append(("scoreboard", "Weekly Scoreboard", "output",
                 scoreboard.to_html("Weekly Scoreboard"),
                 {"agent": "Scorekeeper", "stage": STAGE,
                  "structured": scoreboard.model_dump()}))

    # 2 — Attribution (the internet-enabled duty: real external record)
    attribution = ask(
        "Failure Analysis",
        "You are the Attribution duty (Win/Failure Analysis) of the "
        "Retrospective. Judge the period's DECISIONS against what "
        "subsequently happened — the injected packs are real market "
        "data fetched now; nothing may be cited from memory. The "
        "pivotal split: what was unknowable at decision time vs "
        "knowable but missed. A right decision for the wrong reason "
        "is flagged, not celebrated; a pass that reality vindicated "
        "is still examined for whether the REASONING was sound. End "
        "with the questions the Process Audit panel must answer. "
        "Return STRICT JSON matching:\n"
        + json.dumps(AttributionReport.model_json_schema(), indent=1),
        base + f"\n\nThe Scorekeeper's forensics scope:\n"
        f"{json.dumps(scoreboard.forensics_scope, indent=1)}\n\n"
        f"Post-decision market reality (real, fetched now):\n"
        f"{json.dumps(reality, indent=1)}\n\nRecent headlines:\n"
        f"{news}",
        AttributionReport)
    docs.append(("attribution", "Attribution Report", "output",
                 attribution.to_html("Attribution Report"),
                 {"agent": "Win/Failure Analysis", "stage": STAGE,
                  "structured": attribution.model_dump()}))

    # 3-5 — the Process Audit panel
    audit_context = (
        f"The attribution's questions for you:\n"
        f"{json.dumps(attribution.to_audit, indent=1)}\n\n"
        f"THE ACTUAL RESEARCH MANAGER SYSTEM PROMPT (verbatim from "
        f"code):\n---\n{manager_system_prompt()}\n---\n\n"
        f"Pipeline structure:\n{_structure_description()}\n\n"
        f"Archived Research Manager outputs + reasoning from the run "
        f"ledger (real traces):\n"
        f"{json.dumps(traces, indent=1, default=str)}")
    findings = {}
    for key, agent, lens in AUDITORS:
        findings[key] = ask(
            agent,
            f"You are the {agent} on the Retrospective's Process "
            f"Audit panel. Your lens, and only your lens: {lens}\n\n"
            "Every finding must cite its evidence — a quoted prompt "
            "line, an archived output, a structural fact. Findings "
            "without evidence are discarded upstream. Return STRICT "
            "JSON matching:\n"
            + json.dumps(AuditFinding.model_json_schema(), indent=1),
            base + "\n\n" + audit_context, AuditFinding)
        docs.append((key, TITLES[key], "output",
                     findings[key].to_html(TITLES[key]),
                     {"agent": agent, "stage": STAGE,
                      "structured": findings[key].model_dump()}))

    # 6 — Head of Performance Review (the flow's only deep-think call)
    head = ask(
        "Head of Performance Review",
        "You are the Head of Performance Review — the Retrospective's "
        "judgment. Aggregate across positions and weeks: one miss is "
        "noise; the same gap recurring is signal. Weigh the three "
        "audit lenses against each other, discard unevidenced "
        "findings, and produce: (1) the Performance Assessment — your "
        "considered judgment of the process; (2) the Improvement "
        "Backlog — ranked, evidence-linked, each item implementable "
        "by the Developer Agent as a reviewed commit (the next flow "
        "version). You have NO trading authority; you change the "
        "process, never the book. Be as willing to conclude 'the "
        "process is right, reality offered nothing' as to demand "
        "change — miscalibration claims need evidence, not "
        "impatience. Return STRICT JSON matching:\n"
        + json.dumps(HeadReviewOutput.model_json_schema(), indent=1),
        base + "\n\nScoreboard:\n" + scoreboard.model_dump_json(indent=1)
        + "\n\nAttribution:\n" + attribution.model_dump_json(indent=1)
        + "\n\nAudit findings:\n" + "\n\n".join(
            f"## {TITLES[k]}\n{findings[k].model_dump_json(indent=1)}"
            for k, _, _ in AUDITORS),
        HeadReviewOutput, model=ctx.deep_model,
        reasoning={"max_tokens": 2048})
    docs.append(("performance-assessment", "Performance Assessment",
                 "output",
                 head.assessment.to_html("Performance Assessment"),
                 {"agent": "Head of Performance Review",
                  "stage": STAGE,
                  "structured": head.assessment.model_dump()}))
    docs.append(("improvement-backlog", "Improvement Backlog",
                 "output",
                 head.backlog.to_html("Improvement Backlog"),
                 {"agent": "Head of Performance Review",
                  "stage": STAGE,
                  "structured": head.backlog.model_dump()}))

    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, head
