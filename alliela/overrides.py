"""Per-fund agent overrides.

A user owns their fund's desks: which model an agent thinks with, what
its instructions say, and what it must put in the document it writes.
This module is where those preferences meet the prompt, and it is
deliberately the *only* place — every stage already funnels through
`ask_validated`, so one hook covers the pipeline instead of ten.

Two things stay the engine's, not the user's:

* **The output contract.** Every prompt ends with the document's JSON
  schema because later desks read those fields by name. A replaced
  prompt gets the schema re-attached from the same `schema_json` the
  caller already passes, so a user cannot accidentally delete the one
  paragraph that makes the run parseable.
* **The mandate.** Instructions are how an agent works, not what it is
  allowed to do. The Compliance gate is deterministic code reading the
  fund's typed limits, and nothing written here reaches it.

Models are chosen from a list, never typed. A free-text model field is
an unbounded bill: one confident string and a fund runs 60-odd calls
against the most expensive endpoint on OpenRouter.
"""

# The catalogue is deliberately short: these are the three the pipeline
# already runs on, so every one of them is known to hold up under the
# JSON contract. Adding to this list means having actually run it.
MODEL_CHOICES = [
    ("anthropic/claude-haiku-4.5", "Claude Haiku 4.5",
     "fastest and cheapest — the default for the scanning desks"),
    ("anthropic/claude-sonnet-5", "Claude Sonnet 5",
     "the default deep-think: analysts, debate, risk"),
    ("anthropic/claude-opus-5", "Claude Opus 5",
     "strongest and dearest — the default for PM decisions"),
]
ALLOWED_MODELS = {m for m, _, _ in MODEL_CHOICES}

CONTRACT = ("\n\nReturn STRICT JSON only, no prose around it, matching "
            "this schema:\n")


def _for(ctx, node):
    if not node:
        return None
    return (getattr(ctx, "agent_overrides", None) or {}).get(node)


def resolve_model(ctx, node, model):
    """The override wins, but only if it names a model we vouch for."""
    ov = _for(ctx, node)
    if not ov:
        return model
    chosen = ov.get("model")
    if chosen in ALLOWED_MODELS:
        return chosen
    # An unknown model is ignored rather than raised: a stale row from
    # a retired model must not brick a fund's every future run.
    return model


def resolve_system(ctx, node, system, schema_json=None):
    """The system prompt after the owner's edits, contract intact.

    schema_json=None means the agent answers in prose (the Bull/Bear
    debate turns), so a replaced prompt gets no JSON contract bolted
    onto it — that would tell a debater to argue in JSON."""
    ov = _for(ctx, node)
    if not ov:
        return system
    prompt = (ov.get("prompt") or "").strip()
    if prompt:
        system = prompt + (CONTRACT + schema_json if schema_json else "")
    guidance = (ov.get("output_guidance") or "").strip()
    if guidance:
        system += (
            "\n\nThe fund owner requires the following of the document "
            "you produce. It adds to the schema above, never replaces "
            "it, and it does not loosen any mandate limit:\n" + guidance)
    return system
