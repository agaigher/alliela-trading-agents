"""Tier 01 — Idea Generation. Three desks (Macro, Thematic, Catalyst)
scan the mandate + fresh headlines from their own lens; the Head of
Idea Generation reviews each book (one revision round — the Head does
NOT pick the winner), the desks revise, and the Head compiles the
unranked Combined Ideas Book. 8 LLM calls, matching the pipeline spec.

Output formats are held to the site's sample documents (Macro /
Thematic / Catalyst Ideas Book, Combined Ideas Book)."""
import json

from alliela.documents import CombinedIdeasBook, IdeaBook, RevisionNote
from alliela.market import context_pack

DESKS = [
    ("macro", "Macro Desk",
     "top-down: rates, policy, FX, commodity and supply-chain shifts "
     "that reprice whole groups of names. Work from the macro layer "
     "down to specific listed beneficiaries and casualties."),
    ("thematic", "Thematic Desk",
     "structural: multi-year adoption curves, regulation, technology "
     "cost curves. Find names whose exposure to the theme the market "
     "has not yet priced — second-order beneficiaries beat obvious "
     "pure plays."),
    ("catalyst", "Catalyst Desk",
     "event-driven: dated or expected events — earnings, capital "
     "markets days, policy decisions, index reviews, contract awards — "
     "where the setup into the event is mispriced."),
]

STAGE = "Idea Generation"


def _json_msg(system, user):
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def _desk_system(desk_name, lens, mandate, tip):
    tipline = (f'The firm\'s standing theme instruction for this run: '
               f'"{tip}". A tip focuses the scan; it never overrides '
               f'a mandate limit.' if tip else
               "No theme tip this run — free scan inside the universe.")
    return (
        f"You are the {desk_name} of Alliela Fund 1's Idea Generation "
        f"tier — {lens}\n\n{tipline}\n\n"
        "The fund mandate binds everything you propose (universe, "
        "liquidity floor, shorting rules):\n\n" + mandate + "\n\n"
        "Rules of the desk: propose 2-3 candidates, long or short "
        "(direction is a field, not a fork). Every evidence bullet "
        "must name its source. Claim only edges you can articulate — "
        "'why is the market wrong' beats 'this is a good company'. "
        "Respect the universe and the $8M ADV liquidity floor; note "
        "tradability honestly. Return STRICT JSON only, no prose "
        "around it, matching this schema:\n"
        + json.dumps(IdeaBook.model_json_schema(), indent=1))


def run_ideagen(ctx, llm):
    """Returns (documents, calls, combined_book). documents =
    [(key, title, doc_type, html, meta)]."""
    calls, docs = [], []
    tip = ctx.tip or ""
    news = context_pack(
        [tip or "global energy transition investment",
         "energy transition policy", "grid infrastructure orders"],
        per_query=8)

    def ask(agent, system, user, schema_cls):
        cap = llm.call(model=ctx.quick_model,
                       messages=_json_msg(system, user),
                       agent=agent, stage=STAGE, seq=ctx.next_seq())
        calls.append(cap)
        if ctx.sink:
            ctx.sink.on_call(cap)
        return schema_cls.model_validate(cap.json_text())

    # 1-3: desk drafts
    books = {}
    for key, name, lens in DESKS:
        user = (f"As-of date: {ctx.trade_date}. Fresh headlines for "
                f"context (verify nothing here blindly — they are "
                f"leads, not evidence):\n\n{news}\n\n"
                f"Produce the {name}'s ideas book.")
        books[key] = ask(f"{name}", _desk_system(name, lens,
                                                 ctx.mandate_text, tip),
                         user, IdeaBook)

    # 4: Head reviews all three books, one revision round
    head_sys = (
        "You are the Head of Idea Generation. You do NOT pick winners "
        "— selection is the Selection Committee's job. You review each "
        "desk's book for: evidence discipline (every claim sourced), "
        "mandate fit (universe, liquidity, shorting rules), edge "
        "clarity, and overlap across desks. Return STRICT JSON: a list "
        "of three objects matching this schema:\n"
        + json.dumps(RevisionNote.model_json_schema(), indent=1))
    head_user = "The three books:\n\n" + "\n\n".join(
        f"## {name}\n" + books[key].model_dump_json(indent=1)
        for key, name, _ in DESKS)
    cap = llm.call(model=ctx.quick_model,
                   messages=_json_msg(head_sys, head_user),
                   agent="Head of Idea Generation", stage=STAGE,
                   seq=ctx.next_seq())
    calls.append(cap)
    if ctx.sink:
        ctx.sink.on_call(cap)
    notes = [RevisionNote.model_validate(n) for n in cap.json_text()]
    notes_by_desk = {}
    for n, (key, _, _) in zip(notes, DESKS):
        notes_by_desk[key] = n

    # 5-7: desks revise against the Head's notes
    for key, name, lens in DESKS:
        note = notes_by_desk.get(key)
        user = (f"Your draft book:\n"
                f"{books[key].model_dump_json(indent=1)}\n\n"
                f"The Head of Idea Generation's revision notes:\n"
                f"{note.model_dump_json(indent=1) if note else '(none)'}"
                f"\n\nRevise the book. Address every note; drop "
                f"candidates that cannot survive the notes. Return the "
                f"full revised book as STRICT JSON, same schema.")
        books[key] = ask(name, _desk_system(name, lens,
                                            ctx.mandate_text, tip),
                         user, IdeaBook)

    # 8: Head compiles the Combined Ideas Book (unranked)
    compile_sys = (
        "You are the Head of Idea Generation compiling the revised "
        "books into the Combined Ideas Book. Merge duplicates and "
        "note the overlaps; write an honest coverage note (what the "
        "scan covered, what it deliberately did not). Do NOT rank — "
        "the book is unranked by design. Return STRICT JSON matching:\n"
        + json.dumps(CombinedIdeasBook.model_json_schema(), indent=1))
    compile_user = "The three revised books:\n\n" + "\n\n".join(
        f"## {name}\n" + books[key].model_dump_json(indent=1)
        for key, name, _ in DESKS)
    cap = llm.call(model=ctx.quick_model,
                   messages=_json_msg(compile_sys, compile_user),
                   agent="Head of Idea Generation", stage=STAGE,
                   seq=ctx.next_seq())
    calls.append(cap)
    if ctx.sink:
        ctx.sink.on_call(cap)
    combined = CombinedIdeasBook.model_validate(cap.json_text())

    # documents
    titles = {"macro": "Macro Ideas Book",
              "thematic": "Thematic Ideas Book",
              "catalyst": "Catalyst Ideas Book"}
    for key, name, _ in DESKS:
        docs.append((key, titles[key], "output",
                     books[key].to_html(titles[key]),
                     {"agent": name, "stage": STAGE,
                      "structured": books[key].model_dump()}))
    docs.append(("head", "Combined Ideas Book", "output",
                 combined.to_html("Combined Ideas Book"),
                 {"agent": "Head of Idea Generation", "stage": STAGE,
                  "structured": combined.model_dump()}))
    for key, title, doc_type, html, meta in docs:
        if ctx.sink:
            ctx.sink.on_document(key, title, doc_type, html, meta)
    return docs, calls, combined
