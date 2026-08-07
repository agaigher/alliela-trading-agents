"""Thin OpenRouter client with full capture.

The telemetry contract (trading-agents/CLAUDE.md § "Run telemetry &
output archive") demands the complete provider response — raw JSON,
every reasoning block, generation id, native token counts, cost — per
call. This client exists because framework abstractions normalize
exactly those fields away. One class, one method, everything captured.
"""
import json
import os
import time
from dataclasses import dataclass, field

import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


@dataclass
class CapturedCall:
    """Everything the archive stores about one LLM call."""
    agent: str
    stage: str
    seq: int
    model: str                       # requested
    text: str = ""
    reasoning: list = field(default_factory=list)
    generation_id: str = ""
    provider: str = ""
    resolved_model: str = ""
    finish_reason: str = ""
    usage: dict = field(default_factory=dict)
    cost_usd: float = 0.0
    latency_ms: int = 0
    failures: list = field(default_factory=list)   # retry chain
    raw: dict = field(default_factory=dict)        # untouched response

    def json_text(self):
        """Parse the completion as JSON, tolerating code fences."""
        s = self.text.strip()
        if s.startswith("```"):
            s = s.split("\n", 1)[1] if "\n" in s else s
            s = s.rsplit("```", 1)[0]
        return json.loads(s)


class OpenRouter:
    def __init__(self, api_key=None, timeout=180.0):
        self.api_key = api_key or os.environ["OPENROUTER_API_KEY"]
        self.timeout = timeout

    def call(self, *, model, messages, agent, stage, seq,
             temperature=0.4, max_tokens=8192, retries=3):
        cap = CapturedCall(agent=agent, stage=stage, seq=seq, model=model)
        grew = False           # one automatic retry at 2× on truncation
        body = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "usage": {"include": True},
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "HTTP-Referer": "https://alliela.com",
            "X-Title": "Alliela",
        }
        for attempt in range(1, retries + 1):
            started = time.monotonic()
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(OPENROUTER_URL, json=body,
                                       headers=headers)
                cap.latency_ms = int((time.monotonic() - started) * 1000)
                if resp.status_code in (429, 500, 502, 503) \
                        and attempt < retries:
                    cap.failures.append(
                        {"attempt": attempt, "status": resp.status_code,
                         "body": resp.text[:500]})
                    time.sleep(2 * attempt)
                    continue
                resp.raise_for_status()
                data = resp.json()
                if "error" in data and attempt < retries:
                    cap.failures.append(
                        {"attempt": attempt, "error": data["error"]})
                    time.sleep(2 * attempt)
                    continue
                choice = (data.get("choices") or [{}])[0]
                if (choice.get("finish_reason") == "length"
                        and not grew):
                    grew = True
                    cap.failures.append(
                        {"attempt": attempt, "truncated": True,
                         "max_tokens": body["max_tokens"]})
                    body["max_tokens"] *= 2
                    continue
                cap.raw = data
                msg = choice.get("message") or {}
                cap.text = msg.get("content") or ""
                # every reasoning shape OpenRouter exposes, verbatim
                for k in ("reasoning", "reasoning_details",
                          "reasoning_content"):
                    if msg.get(k):
                        cap.reasoning.append({k: msg[k]})
                cap.generation_id = data.get("id", "")
                cap.provider = data.get("provider", "")
                cap.resolved_model = data.get("model", "")
                cap.finish_reason = choice.get("finish_reason", "")
                cap.usage = data.get("usage") or {}
                cap.cost_usd = float(cap.usage.get("cost") or 0.0)
                return cap
            except httpx.HTTPError as exc:
                cap.latency_ms = int((time.monotonic() - started) * 1000)
                cap.failures.append(
                    {"attempt": attempt, "error": repr(exc)})
                if attempt < retries:
                    time.sleep(2 * attempt)
                    continue
                raise
        raise RuntimeError(f"call failed after {retries} attempts: "
                           f"{cap.failures}")
