"""Every agent's real system prompt, addressable by graph_spec node id.

The portal prefills its editor from this, so an owner edits the actual
text the agent runs on rather than a paraphrase of it. That is the
whole point: a box that starts empty invites you to replace a careful
brief with one sentence, and the agent quietly loses every rule it had.

The prompts themselves live in their stage modules, next to the code
that uses them — this only maps node id to the builder. thesis.py set
the precedent (`manager_system_prompt`, made module-level so the
Retrospective's Prompt Auditor could read the prompt it was auditing);
the rest were lifted to match, verbatim and verified byte-identical.

Rendered for display, the run-time values become placeholders:
`{fund_name}`, `{mandate}` and `{tip}` are substituted when a run
starts (alliela.overrides._fill). Storing an owner's prompt with the
mandate baked in would freeze a copy of it — they would edit the
mandate later and the agent would carry on reading the old one.
"""
from alliela.stages import analysts, execution, ideagen, pm, risk
from alliela.stages import selection, structuring, thesis

# Placeholders, not values: see the module docstring.
FUND = "{fund_name}"
MANDATE = "{mandate}"
TIP = "{tip}"


class _Display:
    """A stand-in run context for rendering a prompt with no run."""
    fund_name = FUND
    mandate_text = MANDATE
    tip = TIP
    trade_date = "{trade_date}"
    restrictions = {}
    book = []


def _desk(key):
    name, lens = next((n, l) for k, n, l in ideagen.DESKS if k == key)
    return lambda ctx: ideagen.desk_system_prompt(
        name, lens, ctx.mandate_text, ctx.tip, ctx.fund_name)


def _sel_lens(key):
    agent, lens, rules = next(
        (a, l, r) for k, a, l, r in selection.LENSES if k == key)
    return lambda ctx: selection.lens_system_prompt(ctx, agent, lens, rules)


def _analyst(key):
    name, lens = next((n, l) for k, n, l in analysts.ANALYSTS if k == key)
    return lambda ctx: analysts.analyst_system_prompt(
        name, lens, ctx.mandate_text, ctx.fund_name)


def _risk_lens(key):
    name, rules = next(
        (n, r) for k, n, r in risk.LENSES if k == key)
    return lambda ctx: risk.lens_system_prompt(ctx, name, rules)


# node id -> (ctx) -> the exact system prompt that agent runs on.
# Compliance is absent deliberately: it is rule code, not a model.
BUILDERS = {
    "macro": _desk("macro"),
    "thematic": _desk("thematic"),
    "catalyst": _desk("catalyst"),
    # The Head has two duties — review the desks, then compile the
    # book. The compile is the one that produces the stage's output, so
    # it is the one an owner edits; the review pass keeps its own
    # prompt (see overrides.OVERRIDE_PRIMARY_ONLY).
    "head-ideagen": lambda ctx: ideagen.head_compile_system_prompt(),
    "conviction": _sel_lens("conviction"),
    "feasibility": _sel_lens("feasibility"),
    "crowding": _sel_lens("crowding"),
    "chair": lambda ctx: selection.chair_system_prompt(),
    "market": _analyst("market"),
    "sentiment": _analyst("sentiment"),
    "news": _analyst("news"),
    "fundamentals": _analyst("fundamentals"),
    "analyst-lead": lambda ctx: analysts.lead_system_prompt(),
    "bull": lambda ctx: thesis.debater_system_prompt("Bull", ctx),
    "bear": lambda ctx: thesis.debater_system_prompt("Bear", ctx),
    "research-manager": lambda ctx: thesis.manager_system_prompt(
        ctx.fund_name),
    "premortem": thesis.premortem_system_prompt,
    "structuring": structuring.structuring_system_prompt,
    "liquidity": _risk_lens("liquidity"),
    "concentration": _risk_lens("concentration"),
    "drawdown": _risk_lens("drawdown"),
    "head-risk": risk.head_system_prompt,
    "pm-decision": pm.decision_system_prompt,
    "pm-funding": pm.funding_system_prompt,
    "pm-instruction": lambda ctx: pm.instruction_system_prompt(),
    "execution": execution.execution_system_prompt,
}


def default_prompt(node_id, ctx=None):
    """The agent's shipped system prompt, or None if it runs no model."""
    build = BUILDERS.get(node_id)
    if build is None:
        return None
    return build(ctx or _Display())
