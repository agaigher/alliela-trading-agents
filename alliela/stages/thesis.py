"""Tier 04 — Thesis Desk. Bull and Bear read the same frozen evidence
and argue opposite sides for three rounds (six alternating turns);
the Research Manager judges the debate decisively — pick a side, never
summarise — and writes the Thesis with dated, decidable kill criteria;
the Pre-mortem then explains, as retrospective fact, how the position
failed. 8 LLM calls, all on the deep-think model; the Manager and
Pre-mortem run with extended reasoning.

Documents held to the sample formats: Bull Case, Bear Case, Investment
Debate Transcript, Thesis, Pre-mortem Review."""
import json

from alliela.documents import (PreMortemReview, Thesis, debate_doc_html,
                               transcript_html)
from alliela.overrides import resolve_model, resolve_system
from alliela.structured import ask_validated

STAGE = "Thesis Desk"
ROUNDS = 3


def manager_system_prompt(fund_name="the fund"):
    """The Research Manager's system prompt — module-level so the
    Retrospective's Prompt Auditor can read the ACTUAL prompt it is
    auditing, not a paraphrase."""
    return (
        f"You are the Research Manager on {fund_name}'s Thesis Desk. "
        "Judge the Bull-Bear debate and produce the Thesis — the "
        "document this fund is named for. Do NOT summarise the debate: "
        "pick the stronger side, ground the verdict in specific "
        "evidence, and resolve the unresolved tensions with a clear "
        "stance. Kill criteria are the v4 discipline: each one dated "
        "and decidable — when the date arrives, the named data source "
        "answers fired or not fired; 'sentiment deteriorates' is not a "
        "kill criterion. If the Bear won, say so: direction is "
        "EXACTLY 'long' or 'pass'. The platform is long only, so a "
        "bearish verdict is 'pass', and so is a withheld or deferred "
        "conviction; the conditions live in stance. "
        "Return STRICT JSON only, matching:\n"
        + json.dumps(Thesis.model_json_schema(), indent=1))


def _msgs(system, user):
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def debater_system_prompt(side, ctx):
    stance = (f"You are the Bull on {ctx.fund_name}'s Thesis Desk, "
              "advocating FOR the position. Build the strongest "
              "evidence-based case for the idea and dismantle the "
              "Bear's arguments directly."
              if side == "Bull" else
              f"You are the Bear on {ctx.fund_name}'s Thesis Desk, "
              "arguing AGAINST the position. Expose the risks, the "
              "over-optimistic assumptions, and the weaknesses in the "
              "Bull's case directly.")
    return (
        f"{stance}\n\nRules of the desk: argue from the frozen analyst "
        "reports — cite specific numbers, dates, and sources from "
        "them; a claim without a citation is conceded. Engage the "
        "opponent's latest turn point by point before adding new "
        "material. Conversational debate prose, 300-450 words per "
        "turn — no JSON, no headers, no bullet lists. The mandate "
        "binds sizing and universe questions:\n\n" + ctx.mandate_text)


def premortem_system_prompt(ctx):
    return (
        f"You are the Pre-mortem on {ctx.fund_name}'s Thesis Desk. It is "
        "twelve months from the as-of date and the position has FAILED. "
        "You are not arguing against the trade — it was made. Explain, "
        "as retrospective fact, why it broke: the failure modes "
        "adversarial debate misses, each with the early signal that "
        "would have shown it first. Return STRICT JSON only, matching:"
        "\n" + json.dumps(PreMortemReview.model_json_schema(),
                          indent=1))


def run_thesis(ctx, llm, brief, reports):
    """Returns (documents, calls, thesis). reports: key→AnalystReport
    from Tier 03."""
    calls, docs = [], []
    evidence = (
        f"The Idea Brief:\n{brief.model_dump_json(indent=1)}\n\n"
        + "\n\n".join(
            f"## {k.title()} Report\n"
            + reports[k].model_dump_json(indent=1)
            for k in ("market", "sentiment", "news", "fundamentals")))

    def call_text(agent, system, user, reasoning=None, node=None):
        # Prose turns, so no schema is passed: the owner's prompt
        # replaces the brief outright rather than gaining a contract.
        cap = llm.call(model=resolve_model(ctx, node, ctx.deep_model),
                       messages=_msgs(resolve_system(ctx, node, system),
                                      user),
                       agent=agent, stage=STAGE, seq=ctx.next_seq(),
                       reasoning=reasoning)
        calls.append(cap)
        if ctx.sink:
            ctx.sink.on_call(cap)
        return cap

    # 1-6: alternating debate, Bull opens
    turns = []            # (speaker, text)
    for rnd in range(ROUNDS):
        for side in ("Bull", "Bear"):
            history = "\n\n".join(f"[{s}]\n{t}" for s, t in turns) \
                or "(you open the debate)"
            user = (f"As-of date: {ctx.trade_date}.\n\nThe evidence "
                    f"(frozen — the debate adds no new data):\n\n"
                    f"{evidence}\n\nDebate so far:\n\n{history}\n\n"
                    f"Round {rnd + 1} of {ROUNDS}. Your turn.")
            cap = call_text(side, debater_system_prompt(side, ctx), user,
                            node=side.lower())
            turns.append((side, cap.text.strip()))

    # 7: Research Manager judges (deep reasoning)
    manager_system = manager_system_prompt(ctx.fund_name)
    transcript_text = "\n\n".join(f"[{s}]\n{t}" for s, t in turns)
    thesis = ask_validated(
        ctx, llm, agent="Research Manager", stage=STAGE,
        node="research-manager",
        system=manager_system,
        user=(f"As-of date: {ctx.trade_date}.\n\nThe evidence:\n\n"
              f"{evidence}\n\nThe full debate:\n\n{transcript_text}"),
        validate=Thesis.model_validate,
        schema_json=json.dumps(Thesis.model_json_schema()),
        model=ctx.deep_model, reasoning={"max_tokens": 2048},
        calls=calls)

    # 8: Pre-mortem (deep reasoning) — prospective hindsight
    premortem_system = premortem_system_prompt(ctx)
    premortem = ask_validated(
        ctx, llm, agent="Pre-mortem", stage=STAGE, node="premortem",
        system=premortem_system,
        user=(f"The Thesis:\n{thesis.model_dump_json(indent=1)}\n\n"
              f"The evidence:\n\n{evidence}"),
        validate=PreMortemReview.model_validate,
        schema_json=json.dumps(PreMortemReview.model_json_schema()),
        model=ctx.deep_model, reasoning={"max_tokens": 2048},
        calls=calls)

    bull_turns = [t for s, t in turns if s == "Bull"]
    bear_turns = [t for s, t in turns if s == "Bear"]
    docs = [
        ("bull", "Bull Case", "output",
         debate_doc_html("Bull", bull_turns),
         {"agent": "Bull", "node": "bull", "stage": STAGE}),
        ("bear", "Bear Case", "output",
         debate_doc_html("Bear", bear_turns),
         {"agent": "Bear", "node": "bear", "stage": STAGE}),
        ("researcher-debate", "Investment Debate Transcript",
         "transcript",
         transcript_html("Investment Debate — Full Transcript", turns),
         {"agent": "Thesis Desk", "stage": STAGE,
          "rounds": ROUNDS}),
        ("research-manager", "Thesis", "output",
         thesis.to_html("Thesis"),
         {"agent": "Research Manager", "node": "research-manager",
          "stage": STAGE,
          "structured": thesis.model_dump()}),
        ("premortem", "Pre-mortem Review", "output",
         premortem.to_html("Pre-mortem Review"),
         {"agent": "Pre-mortem", "node": "premortem", "stage": STAGE,
          "structured": premortem.model_dump()}),
    ]
    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, thesis
