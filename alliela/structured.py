"""Structured-output helper: one call, one validation, and — when a
model emits malformed or schema-violating JSON — exactly one repair
call (quick model) before giving up. The repair call is archived like
any other call; a stage's call count grows honestly when repair fires."""
import json


def ask_validated(ctx, llm, *, agent, stage, system, user, validate,
                  schema_json, model=None, reasoning=None, calls=None):
    """validate: parsed-JSON -> result (raise on invalid).
    Returns the validated result; captured calls are appended to
    `calls` and streamed to ctx.sink."""
    model = model or ctx.quick_model

    def _record(cap):
        if calls is not None:
            calls.append(cap)
        if ctx.sink:
            ctx.sink.on_call(cap)

    cap = llm.call(model=model,
                   messages=[{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                   agent=agent, stage=stage, seq=ctx.next_seq(),
                   reasoning=reasoning)
    _record(cap)
    try:
        return validate(cap.json_text())
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
        return validate(cap2.json_text())
