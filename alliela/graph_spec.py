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
from alliela.stages.analysts import ANALYSTS
from alliela.stages.ideagen import DESKS
from alliela.stages.risk import LENSES as RISK_LENSES
from alliela.stages.selection import LENSES as SELECTION_LENSES

QUICK, DEEP, PM, NONE = "quick", "deep", "pm", "none"

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


def pipeline_spec():
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
                "derived": sid in DERIVED and key in
                           [m[0] for m in DERIVED.get(sid, [])],
            })

    edges = []
    order = [s[1] for s in STAGES]
    for a, b in zip(order, order[1:]):
        edges.append({"from": a, "to": b, "kind": "flow"})
    # The loops the flow actually contains, which a straight line hides.
    edges.append({"from": "compliance", "to": "pm", "kind": "bounce"})
    return {"stages": stages_out, "nodes": nodes, "edges": edges}
