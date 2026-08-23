"""Per-fund agent overrides.

A user owns their fund's desks: which model an agent thinks with, and
what its instructions say. This module is where those preferences meet
the prompt, and it is deliberately the *only* place — every stage
already funnels through `ask_validated`, so one hook covers the
pipeline instead of ten.

The portal prefills its editor with the agent's real prompt (see
alliela.prompts), so an override normally starts life as the shipped
text with an edit in it, not as a blank box. Two things stay the
engine's either way:

* **The output contract.** Later desks read a document's fields by
  name. The prefilled prompt already carries its JSON schema; if an
  owner deletes it, the engine puts one back rather than letting the
  run produce something nothing downstream can read.
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

# Agents whose SECOND duty runs on a different prompt from the one the
# owner edits. Their model override still applies — it is the same
# agent thinking — but replacing a compile prompt with a review prompt
# (or vice versa) would put the wrong instructions on the wrong call.
# The call sites for these pass override_prompt=False.
SECONDARY_DUTIES = {
    "head-ideagen": "reviews the three desk books before compiling them",
    "head-risk": "answers the PM's escalation in the bounce-back round",
}


def _for(ctx, node):
    if not node:
        return None
    return (getattr(ctx, "agent_overrides", None) or {}).get(node)


def _fill(ctx, text):
    """Put the run's real values into the display placeholders.

    A stored prompt keeps `{mandate}` rather than a copy of the mandate
    text: an owner edits their mandate later and every agent should
    read the new one. Plain replace, not str.format — these prompts are
    full of JSON braces.
    """
    return (text
            .replace("{fund_name}", getattr(ctx, "fund_name", "") or "")
            .replace("{mandate}", getattr(ctx, "mandate_text", "") or "")
            .replace("{tip}", getattr(ctx, "tip", "") or ""))


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
    debate turns), so nothing is appended — that would tell a debater
    to argue in JSON.
    """
    ov = _for(ctx, node)
    if not ov:
        return system
    prompt = (ov.get("prompt") or "").strip()
    if not prompt:
        return system
    system = _fill(ctx, prompt)
    # The prefilled prompt already ends in the document's schema, so
    # this normally does nothing. It matters when an owner has deleted
    # it: every JSON Schema dump contains "properties", so its absence
    # means the run would otherwise come back unparseable.
    if schema_json and '"properties"' not in system:
        system += CONTRACT + schema_json
    return system
