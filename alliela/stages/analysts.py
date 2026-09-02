"""Tier 03 — Analyst team. Four specialists build the evidence under
the selected idea, each from real data injected as a context pack AND
from the free tools of their lens (alliela.tools — EDGAR, dated news
with article text, price history, realized and implied vol); the
Analyst Lead audits every report against its brief and writes revision
notes; each specialist gets exactly one revision pass, then the
reports freeze for the Thesis Desk. 9 LLM calls plus one per tool
round trip; up to 6 tool calls per specialist per pass.

Each specialist's tool trail is written as its own evidence document
(`{key}-evidence`). The debate reads the REPORTS — they are the frozen
pack — and the evidence document is the audit trail behind them.

Internal keys follow the site spec (the Positioning analyst's key
stays 'sentiment'). Output formats held to the sample documents
(Market / Positioning / News / Fundamentals Report, Analyst Revision
Notes)."""
import json

from alliela.documents import (AnalystReport, AnalystRevisionNotes,
                               evidence_html)
from alliela.market import (context_pack, price_pack, quote_summary,
                            ticker_snapshot)
from alliela.structured import ask_validated
from alliela.tools import TOOL_BUDGET, TOOLSETS

STAGE = "Analyst Team"

ANALYSTS = [
    ("market", "Market Analyst",
     "price action and market structure: trend, levels, momentum, "
     "volume, where the current price sits against its own history. "
     "What is the market already saying about this name?"),
    ("sentiment", "Positioning Analyst",
     "who owns it and who is against it: institutional/insider "
     "holdings, short interest and borrow, sell-side stance and "
     "targets. Your report verifies (or contradicts) the Selection "
     "Committee's crowding read with data; your borrow findings feed "
     "Pre-Trade Structuring's borrow-realism check downstream."),
    ("news", "News Analyst",
     "the catalyst record and the narrative: what has actually been "
     "announced or reported, dated; how the story the desks told "
     "matches the record; what is scheduled next."),
    ("fundamentals", "Fundamentals Analyst",
     "the numbers under the thesis: growth, margins, returns, "
     "leverage, cash generation, valuation against the claimed "
     "mispricing. Does the arithmetic support the edge?"),
]

TITLES = {"market": "Market Report", "sentiment": "Positioning Report",
          "news": "News Report", "fundamentals": "Fundamentals Report"}


def _msgs(system, user):
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def _packs(brief, trade_date):
    """Real-data context per analyst — fetched deterministically."""
    t = brief.ticker
    qs = quote_summary(t)
    return {
        "market": {"price_pack": price_pack(t),
                   "snapshot": ticker_snapshot(t)},
        "sentiment": {"positioning": qs.get("positioning",
                                            {"status": qs["status"]})},
        "news": {"headlines": context_pack(
            [f"{brief.name} {t}", f"{brief.name} {brief.catalyst}"],
            per_query=10)},
        "fundamentals": {"fundamentals": qs.get(
            "fundamentals", {"status": qs["status"]})},
    }


def analyst_system_prompt(name, lens, mandate, fund_name):
    return (
        f"You are the {name} on {fund_name}'s Analyst team. Your "
        f"lens, and only your lens: {lens}\n\n"
        "Rules: every claim cites its source — the injected data pack, "
        "a tool result (name the tool and the filing or article date), "
        "a dated headline, or is explicitly marked inference. Numbers "
        "you were given or fetched are real; numbers you remember are "
        "not — if neither the pack nor your tools can supply "
        "something, put it in coverage_gaps instead of recalling it.\n"
        f"Tools: you may make up to {TOOL_BUDGET} tool calls this "
        "pass. Spend them on the numbers the thesis actually turns on "
        "— the brief's coverage notes say which — not on what the pack "
        "already holds. A tool that answers 'unavailable' or 'blocked' "
        "is a fact to record, not a reason to guess.\n"
        "Two to four sections of tight prose, a summary table, honest "
        "gaps. The mandate for context:\n\n" + mandate
        + "\n\nReturn STRICT JSON only, matching this schema:\n"
        + json.dumps(AnalystReport.model_json_schema(), indent=1))


def lead_system_prompt():
    return (
        "You are the Analyst Lead. Audit each report against its "
        "brief: does it answer end to end, are claims grounded in "
        "cited evidence (specific numbers, dates, sources), are "
        "coverage gaps honest rather than papered over, does it stay "
        "in its lane? Score 1-10 and write actionable revision "
        "requests — each specialist gets exactly one revision pass. "
        "Return STRICT JSON matching:\n"
        + json.dumps(AnalystRevisionNotes.model_json_schema(),
                     indent=1))


def run_analysts(ctx, llm, brief):
    """Returns (documents, calls, reports: dict key→AnalystReport)."""
    calls, docs = [], []
    packs = _packs(brief, ctx.trade_date)
    brief_json = brief.model_dump_json(indent=1)

    evidence = {key: [] for key, _, _ in ANALYSTS}

    def ask(agent, system, user, schema_cls, node=None, tools=None):
        return ask_validated(
            ctx, llm, agent=agent, stage=STAGE, system=system,
            user=user, validate=schema_cls.model_validate,
            schema_json=json.dumps(schema_cls.model_json_schema()),
            calls=calls, node=node, tools=tools,
            evidence=evidence.get(node) if tools else None)

    # 1-4: specialist drafts
    reports = {}
    for key, name, lens in ANALYSTS:
        user = (f"As-of date: {ctx.trade_date}.\n\nThe Idea Brief from "
                f"the Selection Committee:\n{brief_json}\n\n"
                f"Your data pack (real, fetched now):\n"
                f"{json.dumps(packs[key], indent=1)}\n\n"
                f"Write the {TITLES[key]} (report_type: '{key}').")
        reports[key] = ask(name,
                           analyst_system_prompt(name, lens,
                                           ctx.mandate_text,
                                           ctx.fund_name),
                           user, AnalystReport, node=key,
                           tools=TOOLSETS[key])

    # 5: the Lead audits all four
    lead_system = lead_system_prompt()
    lead_user = (f"The Idea Brief:\n{brief_json}\n\nThe four reports:"
                 + "".join(f"\n\n## {TITLES[k]}\n"
                           + reports[k].model_dump_json(indent=1)
                           for k, _, _ in ANALYSTS))
    notes = ask("Analyst Lead", lead_system, lead_user,
                AnalystRevisionNotes, node="analyst-lead")
    audits = {a.report_type: a for a in notes.audits}

    # 6-9: one revision pass each
    for key, name, lens in ANALYSTS:
        audit = audits.get(key)
        user = (f"Your draft {TITLES[key]}:\n"
                f"{reports[key].model_dump_json(indent=1)}\n\n"
                f"The Analyst Lead's audit:\n"
                f"{audit.model_dump_json(indent=1) if audit else '(none)'}"
                f"\n\nYour data pack, unchanged:\n"
                f"{json.dumps(packs[key], indent=1)}\n\n"
                f"Revise the report. Address every revision request "
                f"without inventing data: you have a fresh tool budget "
                f"for this pass — use it to close the gaps the Lead "
                f"named, and record as a coverage gap whatever the "
                f"tools cannot reach. Return the full revised report "
                f"as STRICT JSON, same schema.")
        reports[key] = ask(name,
                           analyst_system_prompt(name, lens,
                                           ctx.mandate_text,
                                           ctx.fund_name),
                           user, AnalystReport, node=key,
                           tools=TOOLSETS[key])

    for key, name, _ in ANALYSTS:
        docs.append((key, TITLES[key], "output",
                     reports[key].to_html(TITLES[key]),
                     {"agent": name, "node": key, "stage": STAGE,
                      "structured": reports[key].model_dump()}))
    docs.append(("analyst-lead", "Analyst Revision Notes", "output",
                 notes.to_html("Analyst Revision Notes"),
                 {"agent": "Analyst Lead", "node": "analyst-lead", "stage": STAGE,
                  "structured": notes.model_dump()}))
    # The audit trail behind each report: one evidence document per
    # specialist, both passes. Written even when empty — "called
    # nothing" is a finding the Retrospective should see.
    for key, name, _ in ANALYSTS:
        trail = evidence[key]
        docs.append((f"{key}-evidence", f"{TITLES[key]} — Evidence",
                     "evidence",
                     evidence_html(f"{TITLES[key]} — Evidence", trail,
                                   TOOL_BUDGET * 2),
                     {"agent": name, "node": key, "stage": STAGE,
                      "structured": {"calls": len(trail),
                                     "tools": sorted({e["tool"]
                                                      for e in trail}),
                                     "entries": trail}}))
    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, reports
