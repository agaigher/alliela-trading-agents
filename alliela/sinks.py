"""Sink protocol — the engine/serving boundary.

The engine emits captured calls and documents; whoever runs it decides
where they go. The api/ worker supplies Postgres sinks (private); this
package ships only a file sink so the open-source engine is complete
on its own."""
import json
import pathlib


class FileSink:
    """Writes runs/<run_id>/ — calls as JSONL, documents as HTML."""

    def __init__(self, root="runs", run_id="local"):
        self.dir = pathlib.Path(root) / run_id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._calls = (self.dir / "calls.jsonl").open("a",
                                                      encoding="utf-8")

    def on_call(self, cap):
        rec = {"agent": cap.agent, "stage": cap.stage, "seq": cap.seq,
               "model": cap.model, "generation_id": cap.generation_id,
               "provider": cap.provider,
               "resolved_model": cap.resolved_model,
               "finish_reason": cap.finish_reason, "usage": cap.usage,
               "cost_usd": cap.cost_usd, "latency_ms": cap.latency_ms,
               "text": cap.text, "reasoning": cap.reasoning,
               "failures": cap.failures, "raw": cap.raw}
        self._calls.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self._calls.flush()

    def on_document(self, key, title, doc_type, html, meta):
        (self.dir / f"{key}.html").write_text(html, encoding="utf-8")
        (self.dir / f"{key}.meta.json").write_text(
            json.dumps({"title": title, "doc_type": doc_type,
                        **meta}, ensure_ascii=False), encoding="utf-8")

    def finalize(self, rollup):
        (self.dir / "rollup.json").write_text(
            json.dumps(rollup, ensure_ascii=False, indent=1),
            encoding="utf-8")
        self._calls.close()
