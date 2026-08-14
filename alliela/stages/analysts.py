"""Tier 03 — Analyst team. Four specialists build the evidence under
the selected idea, each from real data injected as a context pack; the
Analyst Lead audits every report against its brief and writes revision
notes; each specialist gets exactly one revision pass, then the
reports freeze for the Thesis Desk. 9 LLM calls.

Internal keys follow the site spec (the Positioning analyst's key
stays 'sentiment'). Output formats held to the sample documents
(Market / Positioning / News / Fundamentals Report, Analyst Revision
Notes)."""
import json

from alliela.documents import AnalystReport, AnalystRevisionNotes
from alliela.market import (context_pack, price_pack, quote_summary,
                            ticker_snapshot)

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


def _analyst_system(name, lens, mandate):
    return (
        f"You are the {name} on Alliela Fund 1's Analyst team. Your "
        f"lens, and only your lens: {lens}\n\n"
        "Rules: every claim cites its source — the injected data pack, "
        "a dated headline, or is explicitly marked inference. Numbers "
        "you were given are real; numbers you remember are not — if "
        "the pack lacks something, put it in coverage_gaps instead of "
        "recalling it. Two to four sections of tight prose, a summary "
        "table, honest gaps. The mandate for context:\n\n" + mandate
        + "\n\nReturn STRICT JSON only, matching this schema:\n"
        + json.dumps(AnalystReport.model_json_schema(), indent=1))


def run_analysts(ctx, llm, brief):
    """Returns (documents, calls, reports: dict key→AnalystReport)."""
    calls, docs = [], []
    packs = _packs(brief, ctx.trade_date)
    brief_json = brief.model_dump_json(indent=1)

    def ask(agent, system, user, schema_cls):
        cap = llm.call(model=ctx.quick_model,
                       messages=_msgs(system, user),
                       agent=agent, stage=STAGE, seq=ctx.next_seq())
        calls.append(cap)
        if ctx.sink:
            ctx.sink.on_call(cap)
        return schema_cls.model_validate(cap.json_text())

    # 1-4: specialist drafts
    reports = {}
    for key, name, lens in ANALYSTS:
        user = (f"As-of date: {ctx.trade_date}.\n\nThe Idea Brief from "
                f"the Selection Committee:\n{brief_json}\n\n"
                f"Your data pack (real, fetched now):\n"
                f"{json.dumps(packs[key], indent=1)}\n\n"
                f"Write the {TITLES[key]} (report_type: '{key}').")
        reports[key] = ask(name,
                           _analyst_system(name, lens,
                                           ctx.mandate_text),
                           user, AnalystReport)

    # 5: the Lead audits all four
    lead_system = (
        "You are the Analyst Lead. Audit each report against its "
        "brief: does it answer end to end, are claims grounded in "
        "cited evidence (specific numbers, dates, sources), are "
        "coverage gaps honest rather than papered over, does it stay "
        "in its lane? Score 1-10 and write actionable revision "
        "requests — each specialist gets exactly one revision pass. "
        "Return STRICT JSON matching:\n"
        + json.dumps(AnalystRevisionNotes.model_json_schema(),
                     indent=1))
    lead_user = (f"The Idea Brief:\n{brief_json}\n\nThe four reports:"
                 + "".join(f"\n\n## {TITLES[k]}\n"
                           + reports[k].model_dump_json(indent=1)
                           for k, _, _ in ANALYSTS))
    notes = ask("Analyst Lead", lead_system, lead_user,
                AnalystRevisionNotes)
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
                f"without inventing data the pack does not contain. "
                f"Return the full revised report as STRICT JSON, same "
                f"schema.")
        reports[key] = ask(name,
                           _analyst_system(name, lens,
                                           ctx.mandate_text),
                           user, AnalystReport)

    for key, name, _ in ANALYSTS:
        docs.append((key, TITLES[key], "output",
                     reports[key].to_html(TITLES[key]),
                     {"agent": name, "stage": STAGE,
                      "structured": reports[key].model_dump()}))
    docs.append(("analyst-lead", "Analyst Revision Notes", "output",
                 notes.to_html("Analyst Revision Notes"),
                 {"agent": "Analyst Lead", "stage": STAGE,
                  "structured": notes.model_dump()}))
    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, reports
