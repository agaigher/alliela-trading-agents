"""Run context — everything a stage needs, injected by the runner
(the api/ worker in production, a local driver in development)."""
from dataclasses import dataclass, field


@dataclass
class RunContext:
    run_id: str
    fund_id: str
    flow_version: str
    engine_commit: str
    mandate_text: str            # the full mandate, verbatim
    tip: str                     # standing theme instruction ('' = free)
    trade_date: str              # YYYY-MM-DD as-of
    sink: object = None          # sinks protocol
    quick_model: str = "anthropic/claude-haiku-4.5"
    deep_model: str = "anthropic/claude-sonnet-5"
    seq: int = field(default=0)

    def next_seq(self):
        self.seq += 1
        return self.seq
