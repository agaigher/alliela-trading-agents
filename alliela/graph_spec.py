"""A structural description of the origination pipeline, derived from
the stages themselves.

The portal draws a clickable graph from this, and P4's interpreter will
eventually execute from a document of the same shape. It is built by
importing each stage's own agent constants rather than re-typing them:
a hand-authored picture drifts from the code the moment a desk is added,
and a graph that lies about the pipeline is worse than no graph.

What is still authored here: the stage order, the edges between stages,
and the single-agent stages whose names live inside their prompts. Those
are the parts the code does not currently declare — and the honest place
to notice that is here, not in a React component.
"""
from alliela.context import RunContext
from alliela.overrides import MODEL_CHOICES, SECONDARY_DUTIES
from alliela.prompts import default_prompt
from alliela.stages.analysts import ANALYSTS
from alliela.stages.ideagen import DESKS
from alliela.stages.risk import LENSES as RISK_LENSES
from alliela.stages.selection import LENSES as SELECTION_LENSES

QUICK, DEEP, PM, NONE = "quick", "deep", "pm", "none"

# What each tier actually resolves to, read off RunContext's own
# defaults rather than restated — the portal shows a user which model
# an agent runs on today, and a second copy of these strings would
# start lying the first time one of them is changed.
_FIELDS = RunContext.__dataclass_fields__
TIER_MODEL = {
    QUICK: _FIELDS["quick_model"].default,
    DEEP: _FIELDS["deep_model"].default,
    PM: _FIELDS["pm_model"].default,
    NONE: None,
}

STAGES = [
    ("01", "ideagen", "Idea Generation"),
    ("02", "selection", "Selection Committee"),
    ("03", "analysts", "Analyst Team"),
    ("04", "thesis", "Thesis Desk"),
    ("05", "structuring", "Pre-Trade Structuring"),
    ("06", "risk", "Risk Panel"),
    ("07", "pm", "Portfolio Manager"),
    ("08", "compliance", "Compliance"),
    ("09", "execution", "Execution"),
]

# Stages whose agents are not declared as a constant: their identity
# lives inside the prompt text. Listed explicitly so the graph is
# complete, and marked so it is obvious which half is derived.
AUTHORED = {
    "thesis": [
        ("bull", "Bull", DEEP, "argues the long case from the frozen "
         "analyst evidence, three rounds, cite-or-concede"),
        ("bear", "Bear", DEEP, "argues the short case on the same "
         "evidence, three rounds"),
        ("research-manager", "Research Manager", DEEP, "judges the "
         "debate into a Thesis with dated, decidable kill criteria"),
        ("premortem", "Pre-mortem", DEEP, "writes prospective hindsight: "
         "it is a year on and the position failed"),
    ],
    "structuring": [
        ("structuring", "Trading Desk", DEEP, "turns a non-pass thesis "
         "into a Transaction Proposal: tranches, participation vs "
         "verified ADV, stop, borrow-realism check"),
    ],
    "pm": [
        ("pm-decision", "PM - Decision", PM, "addresses every signed "
         "constraint or escalates; declining is first-class"),
        ("pm-funding", "PM - Funding", PM, "cash first, then trims the "
         "lowest-conviction holdings"),
        ("pm-instruction", "PM - Instruction", PM, "binds decision and "
         "funding into the Dealing Instruction"),
    ],
    "compliance": [
        ("compliance", "Compliance gate", NONE, "deterministic rule "
         "code, no model: the mandate's typed limits against the book "
         "at order release"),
    ],
    "execution": [
        ("execution", "Execution", DEEP, "paper fills at verified "
         "prices; the only write to the book"),
    ],
}

# Leads that a stage's constant does not include.
LEADS = {
    "ideagen": ("head-ideagen", "Head of Idea Generation", QUICK,
                "reviews all three books, one revision round, then "
                "compiles the unranked Combined Ideas Book"),
    "selection": ("chair", "Selection Chair", QUICK,
                  "aggregates the three lenses by judgment - a fatal "
                  "score in any lens eliminates - and writes the Idea "
                  "Brief"),
    "analysts": ("analyst-lead", "Analyst Lead", QUICK,
                 "audits all four reports and demands one revision pass"),
    "risk": ("head-risk", "Head of Risk", DEEP,
             "signs the typed RiskConstraints, binding on the PM; may "
             "veto outright"),
}

DERIVED = {
    "ideagen": [(k, name, QUICK, brief) for k, name, brief in DESKS],
    "selection": [(k, name, QUICK, rules[:120])
                  for k, name, _lens, rules in SELECTION_LENSES],
    "analysts": [(k, name, QUICK, brief) for k, name, brief in ANALYSTS],
    "risk": [(k, name, DEEP, brief) for k, name, brief in RISK_LENSES],
}


def _origination():
    """{stages, nodes, edges} for the origination flow."""
    nodes, stages_out = [], []
    for tier, sid, title in STAGES:
        members = list(DERIVED.get(sid, [])) + list(AUTHORED.get(sid, []))
        if sid in LEADS:
            members.append(LEADS[sid])
        stages_out.append({"id": sid, "tier": tier, "title": title,
                           "nodes": [m[0] for m in members]})
        for key, name, tier_model, brief in members:
            nodes.append({
                "id": key, "stage": sid, "stage_title": title,
                "name": name, "model_tier": tier_model,
                "brief": brief.strip(),
                "default_model": TIER_MODEL[tier_model],
                # The exact text this agent runs on, with the run-time
                # values left as {fund_name} / {mandate} / {tip}. The
                # portal prefills its editor from this, so an owner
                # edits the real prompt rather than a blank box.
                "default_prompt": default_prompt(key),
                "second_duty": SECONDARY_DUTIES.get(key),
                "derived": sid in DERIVED and key in
                           [m[0] for m in DERIVED.get(sid, [])],
            })

    # Node-level edges, matching the flow the marketing graph draws
    # (web/pages/home.py GRAPH_EDGES) and the pipeline actually runs.
    # Stage-to-stage lines were a lie of convenience: the analysts feed
    # BOTH the Lead and the debaters, and the desks fan out from one
    # head rather than from whichever node happened to be last.
    edges = [(a, b, "flow") for a, b in [
        ("macro", "head-ideagen"), ("thematic", "head-ideagen"),
        ("catalyst", "head-ideagen"),
        ("head-ideagen", "conviction"), ("head-ideagen", "feasibility"),
        ("head-ideagen", "crowding"),
        ("conviction", "chair"), ("feasibility", "chair"),
        ("crowding", "chair"),
        ("chair", "market"), ("chair", "sentiment"),
        ("chair", "news"), ("chair", "fundamentals"),
        ("market", "analyst-lead"), ("sentiment", "analyst-lead"),
        ("news", "analyst-lead"), ("fundamentals", "analyst-lead"),
        # the frozen reports feed both debaters directly
        ("market", "bull"), ("sentiment", "bull"),
        ("news", "bull"), ("fundamentals", "bull"),
        ("market", "bear"), ("sentiment", "bear"),
        ("news", "bear"), ("fundamentals", "bear"),
        ("bull", "research-manager"), ("bear", "research-manager"),
        ("research-manager", "premortem"),
        # the thesis contains the pre-mortem, so the desk hears from the
        # manager — there is no separate premortem handoff
        ("research-manager", "structuring"),
        ("structuring", "liquidity"), ("structuring", "concentration"),
        ("structuring", "drawdown"),
        # three lenses debate, one Head carries the constraints
        ("liquidity", "head-risk"), ("concentration", "head-risk"),
        ("drawdown", "head-risk"),
        ("head-risk", "pm-decision"),
        ("pm-decision", "pm-funding"),
        ("pm-funding", "pm-instruction"),
        ("pm-instruction", "compliance"),
        ("compliance", "execution"),
    ]]

    # Loops the straight line hides. rounds=None means "as many times as
    # it fails" — a compliance breach returns a new decision, not a
    # quietly edited instruction.
    for src, dst, kind, rounds in [
        ("head-ideagen", "macro", "review", 1),
        ("head-ideagen", "thematic", "review", 1),
        ("head-ideagen", "catalyst", "review", 1),
        ("analyst-lead", "market", "review", 1),
        ("analyst-lead", "sentiment", "review", 1),
        ("analyst-lead", "news", "review", 1),
        ("analyst-lead", "fundamentals", "review", 1),
        ("bull", "bear", "debate", 3),
        ("pm-decision", "head-risk", "bounce", 1),
        ("compliance", "pm-decision", "bounce", None),
    ]:
        edges.append((src, dst, kind, rounds))

    edges = [
        {"from": e[0], "to": e[1], "kind": e[2],
         "rounds": (e[3] if len(e) > 3 else None)}
        for e in edges
    ]
    return {
        "id": "origination",
        "title": "Origination",
        "subtitle": "From a theme to a position. Nine tiers, roughly "
                    "60 model calls, about fifteen minutes.",
        "stages": stages_out,
        "nodes": nodes,
        "edges": edges,
    }


# ── The management flow (alliela/stages/daily.py) ────────────────────
#
# "Origination deliberates, management executes discipline." Fast, no
# debate: anything that needs arguing escalates back to origination.
#
# Authored rather than derived because the duties are not declared as a
# constant — their identity lives in their prompts, same as the
# origination stages in AUTHORED above. The EDGES, though, are read off
# what each duty is actually handed in daily.py, not off the tier
# order: the Portfolio Review is given every duty report AND every
# verdict, so it has five inputs, not one.
DAILY_STAGES = [
    ("01", "intel", "Intelligence Duties"),
    ("02", "verdicts", "Position Verdicts"),
    ("03", "review", "Portfolio Review"),
    ("04", "daily-compliance", "Compliance"),
    ("05", "daily-execution", "Execution"),
]

DAILY_NODES = {
    "intel": [
        ("market-context", "Market Context", QUICK,
         "the outside world in one pass, whole book: headlines and "
         "real snapshots, no per-name opinion"),
        ("risk-report", "Risk Report", QUICK,
         "origination's three risk lenses re-checked daily against the "
         "live book, plus the squeeze watch on every short"),
        ("thesis-check", "Thesis Check", QUICK,
         "one position at a time: the dated kill criteria evaluated "
         "fired / approaching / not_fired - decidable, not vibes"),
        ("pnl-review", "P&L Review", QUICK,
         "the move against each thesis's EXPECTATION, never raw P&L - "
         "up can be off-thesis, down can be on-path"),
    ],
    "verdicts": [
        ("position-review", "Position Review", QUICK,
         "the PM's per-position verdict: Hold, Add, Trim, Exit. Cannot "
         "originate names; an Add past the 2% guardrail escalates"),
    ],
    "review": [
        ("portfolio-review", "Portfolio Review", DEEP,
         "the loop's only deep-think seat: reads every duty and every "
         "verdict, may override any of them, binds the Rebalance "
         "Instruction (empty is a first-class answer)"),
    ],
    "daily-compliance": [
        ("daily-compliance", "Daily Compliance gate", NONE,
         "deterministic rule code: the mandate's typed limits plus the "
         "loop's own guardrails, checked at order release"),
    ],
    "daily-execution": [
        ("execution", "Execution", DEEP,
         "paper fills at verified prices - the same Execution seat "
         "origination uses, shared rather than duplicated"),
    ],
}

DAILY_EDGES = [
    # Each duty reads what daily.py actually hands it.
    ("market-context", "risk-report"), ("market-context", "pnl-review"),
    ("risk-report", "position-review"),
    ("thesis-check", "position-review"),
    ("pnl-review", "position-review"),
    # The Portfolio Review is given the four duty reports as well as
    # the verdicts, so a line straight from Position Review alone would
    # understate what it reads.
    ("market-context", "portfolio-review"),
    ("risk-report", "portfolio-review"),
    ("thesis-check", "portfolio-review"),
    ("pnl-review", "portfolio-review"),
    ("position-review", "portfolio-review"),
    ("portfolio-review", "daily-compliance"),
    ("daily-compliance", "execution"),
]


def _management():
    nodes, stages_out = [], []
    for tier, sid, title in DAILY_STAGES:
        members = DAILY_NODES[sid]
        stages_out.append({"id": sid, "tier": tier, "title": title,
                           "nodes": [m[0] for m in members]})
        for key, name, tier_model, brief in members:
            nodes.append({
                "id": key, "stage": sid, "stage_title": title,
                "name": name, "model_tier": tier_model,
                "brief": brief.strip(),
                "default_model": TIER_MODEL[tier_model],
                "default_prompt": default_prompt(key),
                "second_duty": SECONDARY_DUTIES.get(key),
                "derived": False,
            })
    return {
        "id": "management",
        "title": "Management",
        "subtitle": "Origination deliberates; management executes "
                    "discipline. No debate - anything worth arguing "
                    "escalates back to origination.",
        "stages": stages_out,
        "nodes": nodes,
        "edges": [{"from": a, "to": b, "kind": "flow", "rounds": None}
                  for a, b in DAILY_EDGES],
    }


def pipeline_spec():
    """Every flow the engine runs, plus the models an owner may pick.

    Two flows today. `execution` appears in both by design: it is one
    seat that both flows hand an instruction to, so an override on it
    applies wherever it runs — duplicating it under a second id would
    promise a distinction the engine does not make.
    """
    return {
        "flows": [_origination(), _management()],
        # The models an owner may pick from. A list, not a text box:
        # see alliela/overrides.py on why.
        "models": [{"id": m, "name": n, "note": note}
                   for m, n, note in MODEL_CHOICES],
    }
