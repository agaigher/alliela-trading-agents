"""Structured-output helper: one call, one validation, and — when a
model emits malformed or schema-violating JSON — exactly one repair
call (quick model) before giving up. The repair call is archived like
any other call; a stage's call count grows honestly when repair fires."""
import json

from alliela.overrides import resolve_model, resolve_system


def ask_validated(ctx, llm, *, agent, stage, system, user, validate,
                  schema_json, model=None, reasoning=None, calls=None,
                  node=None, override_prompt=True):
    """validate: parsed-JSON -> result (raise on invalid).
    Returns the validated result; captured calls are appended to
    `calls` and streamed to ctx.sink.

    node: the graph_spec node id, so the fund owner's overrides for
    this agent can be applied. Omitted = ships as written.

    override_prompt=False: this is the agent's SECOND duty and runs on
    a different prompt from the one the owner edits, so take their
    model but not their instructions (alliela.overrides
    SECONDARY_DUTIES)."""
    # The owner's overrides land here, at the single point every
    # stage passes through, so no stage has to know they exist.
    if override_prompt:
        system = resolve_system(ctx, node, system, schema_json)
    model = resolve_model(ctx, node, model) or ctx.quick_model

    def _record(cap):
        if calls is not None:
            calls.append(cap)
        if ctx.sink:
            ctx.sink.on_call(cap)

    # Node lifecycle. Emitted here for the same reason the overrides
    # hook lives here: every stage funnels through this function, so
    # one edit covers the pipeline instead of ten. A call is archived
    # only once it RETURNS, which makes "started" unknowable from the
    # archive alone — and an agent that is thinking for ninety seconds
    # is exactly the one a watcher wants to see.
    _node(ctx, node, stage, agent, "running")

    cap = llm.call(model=model,
                   messages=[{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                   agent=agent, stage=stage, seq=ctx.next_seq(),
                   reasoning=reasoning)
    _record(cap)
    try:
        result = validate(cap.json_text())
    except Exception as exc:
        repair_system = (
            "You repair malformed JSON. Output ONLY the corrected, "
            "valid JSON — no prose, no code fences, no commentary. "
            "Preserve the content; fix only the structure.")
        repair_user = (
            f"This output failed with: {exc}\n\n"
            f"It must be valid JSON matching this schema:\n"
            f"{schema_json}\n\nBroken output:\n{cap.text}")
        cap2 = llm.call(model=ctx.quick_model,
                        messages=[{"role": "system",
                                   "content": repair_system},
                                  {"role": "user",
                                   "content": repair_user}],
                        agent=f"{agent} (repair)", stage=stage,
                        seq=ctx.next_seq())
        _record(cap2)
        # Still inside the agent's turn: repair is this agent failing
        # and recovering, not a new one starting. Marking it done only
        # after the repair validates keeps the two honest.
        result = validate(cap2.json_text())
        _node(ctx, node, stage, agent, "done")
        return result
    _node(ctx, node, stage, agent, "done")
    return result


def note_node(ctx, node, stage, agent, state):
    """The lifecycle emit, for stages that never reach ask_validated.

    The Compliance gate is rule code with no model call, so without
    this its node would be the one seat on the graph that never lights
    up — and the deterministic gate is precisely the step a watcher
    most wants confirmation of.
    """
    _node(ctx, node, stage, agent, state)


def _node(ctx, node, stage, agent, state):
    """Tell the sink an agent started or finished.

    Optional throughout: `node` is None for the agents whose id the
    graph does not carry, and a sink predating this protocol has no
    `on_node`. Neither is worth failing a paid run over, so both are
    skipped rather than raised — a run that completes with a gap in
    its progress bar beats a run that dies reporting one.
    """
    if not node or not ctx.sink:
        return
    fn = getattr(ctx.sink, "on_node", None)
    if fn is None:
        return
    try:
        fn(node, stage, agent, state)
    except Exception as exc:
        print(f"sink.on_node({node}, {state}) failed: {exc}")
