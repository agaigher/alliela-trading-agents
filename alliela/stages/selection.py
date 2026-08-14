"""Tier 02 — Selection Committee. Three scorers each judge every
candidate through a single lens (edge, feasibility, crowding); the
Chair aggregates by judgment — a fatal score in any lens eliminates —
forces the ranking, and writes the Idea Brief the Analyst team kicks
off from. 4 LLM calls.

The feasibility lens runs on REAL data: every candidate ticker is
verified against Yahoo Finance (resolves? price? average daily value
traded vs the mandate's $8M floor?) before the scorer sees it — the
gate that kills hallucinated names with evidence, not vibes.

Output formats held to the site's sample documents (Edge / Feasibility
/ Crowding Scorecard, Idea Brief)."""
import json

from alliela.documents import IdeaBrief, Scorecard
from alliela.market import ticker_snapshot
from alliela.structured import ask_validated

STAGE = "Selection Committee"

LENSES = [
    ("conviction", "Edge Scorer", "edge",
     "Size of the claimed edge × strength of early evidence. You are a "
     "TRIAGE signal: your score expires the moment the Analyst Reports "
     "land and may never be cited downstream as evidence. Fatal = no "
     "articulable reason the market is wrong (a good company is not "
     "an edge)."),
    ("feasibility", "Feasibility Scorer", "feasibility",
     "Liquidity, data coverage, tradability — judged on the VERIFIED "
     "market data provided, not on the desks' claims. Fatal rules: a "
     "ticker whose verification status is 'not_found' is a fantasy "
     "name — always fatal; average daily value traded below the "
     "mandate's $8M floor — fatal; venue outside the mandate universe "
     "— fatal. 'data_unavailable' is NEVER fatal: score conservatively "
     "and flag the coverage gap. Also flag any name/ticker mismatch "
     "between a desk's claim and the verified name."),
    ("crowding", "Crowding Scorer", "crowding",
     "Consensus and positioning: how owned, how obvious, how discussed "
     "is this idea? A crowded trade can still score 3 if the edge is "
     "differentiated; fatal = the idea IS the consensus with no "
     "variant perception at all."),
]


def _msgs(system, user):
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def run_selection(ctx, llm, combined):
    """Returns (documents, calls, brief)."""
    calls, docs = [], []
    candidates = [c.model_dump() for c in combined.candidates]

    # real verification pack — fetched deterministically, injected
    snapshots = [ticker_snapshot(c.ticker) for c in combined.candidates]

    def ask(agent, system, user, schema_cls):
        return ask_validated(
            ctx, llm, agent=agent, stage=STAGE, system=system,
            user=user, validate=schema_cls.model_validate,
            schema_json=json.dumps(schema_cls.model_json_schema()),
            calls=calls)

    cards = {}
    for key, agent, lens, lens_rules in LENSES:
        system = (
            f"You are the {agent} of Alliela Fund 1's Selection "
            f"Committee. You judge EVERY candidate through exactly one "
            f"lens — {lens} — and nothing else.\n\nLens rules: "
            f"{lens_rules}\n\nThe mandate (universe, liquidity floor, "
            f"shorting rules) binds:\n\n{ctx.mandate_text}\n\n"
            "Score every candidate 1-5 through your lens, mark fatal "
            "flags per your rules, keep rationales to two sentences. "
            "Return STRICT JSON only, matching this schema:\n"
            + json.dumps(Scorecard.model_json_schema(), indent=1))
        user = (f"As-of date: {ctx.trade_date}.\n\nThe Combined Ideas "
                f"Book candidates:\n{json.dumps(candidates, indent=1)}")
        if lens == "feasibility":
            user += ("\n\nVERIFIED market data (real, fetched now — "
                     "trust this over any desk claim):\n"
                     + json.dumps(snapshots, indent=1))
        cards[key] = ask(agent, system, user, Scorecard)

    chair_system = (
        "You are the Chair of the Selection Committee. Aggregate the "
        "three scorecards BY JUDGMENT, never by summing scores: a "
        "fatal flag in any lens eliminates that candidate outright; "
        "among survivors, weigh the lenses as the situation demands "
        "and force a ranking. Select exactly ONE idea (one idea per "
        "run) and write the Idea Brief the Analyst team kicks off "
        "from: catalyst, rationale, what the analysts must verify "
        "first, and the ranked rejects with honest reasons. If no "
        "candidate survives, say so (viable=false) — a no-trade run "
        "is a first-class outcome. Remember: edge scores are triage "
        "and expire downstream. Return STRICT JSON matching:\n"
        + json.dumps(IdeaBrief.model_json_schema(), indent=1))
    chair_user = (
        f"Candidates:\n{json.dumps(candidates, indent=1)}\n\n"
        f"Verified market data:\n{json.dumps(snapshots, indent=1)}\n\n"
        + "\n\n".join(
            f"## {agent} ({lens})\n"
            + cards[key].model_dump_json(indent=1)
            for key, agent, lens, _ in LENSES))
    brief = ask("Selection Chair", chair_system, chair_user, IdeaBrief)

    titles = {"conviction": "Edge Scorecard",
              "feasibility": "Feasibility Scorecard",
              "crowding": "Crowding Scorecard"}
    for key, agent, lens, _ in LENSES:
        docs.append((key, titles[key], "output",
                     cards[key].to_html(titles[key]),
                     {"agent": agent, "stage": STAGE,
                      "structured": cards[key].model_dump()}))
    docs.append(("chair", "Idea Brief", "output",
                 brief.to_html("Idea Brief"),
                 {"agent": "Selection Chair", "stage": STAGE,
                  "structured": brief.model_dump(),
                  "verified_snapshots": snapshots}))
    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, brief
