# `trading-agents/` CLAUDE guidance

This folder is the multi-agent LLM hedge-fund framework — the new Alliela
product backend. **Vendored** from `TauricResearch/TradingAgents` via
`git subtree --squash`, then stripped down to the absolute minimum needed
to run the pipeline as a library from the terminal.

## Key facts

- Runtime: local Python process for now. A FastAPI / web shim will sit on
  top of the library surface later.
- Origin: [`https://github.com/TauricResearch/TradingAgents`](https://github.com/TauricResearch/TradingAgents) (`main` branch). Apache 2.0.
- Stack: Python 3.12, LangGraph, multi-provider LLMs (OpenAI / Anthropic /
  Gemini / xAI / DeepSeek / Qwen / GLM / MiniMax).
- Entry: programmatic — `from tradingagents.graph.trading_graph import TradingAgentsGraph`.
  See [`main.py`](main.py) for a minimal usage example.

## Contents

The vendored folder has been trimmed to **only** what's needed to run the
framework as a library:

```
trading-agents/
├── CLAUDE.md              ← this file
├── .env.example           ← template for API keys
├── .gitignore             ← Python + tooling hygiene
├── main.py                ← minimal driver: invokes the graph on NVDA
├── pyproject.toml         ← package metadata + dependency list
└── tradingagents/         ← the actual framework (library code)
    ├── default_config.py     all configurable knobs
    ├── agents/               analyst · researcher · trader · risk · manager prompts
    ├── graph/                LangGraph setup, conditional routing, trading_graph
    ├── dataflows/            yfinance · alpha_vantage · reddit · stocktwits
    ├── llm_clients/          provider wrappers
    └── ...
```

## Local-run workflow

```bash
cd trading-agents
python -m venv .venv
source .venv/bin/activate          # or .venv\Scripts\activate on Windows
pip install -e .
cp .env.example .env                # then fill in API keys
python main.py
```

`main.py` builds the graph and runs a single analysis on `NVDA` for
`2024-05-10`. Adjust the ticker/date or import `TradingAgentsGraph`
elsewhere for your own driver.

## Per-agent model selection (Alliela addition)

`config["agent_models"]` maps an agent key to a model name, overriding that
agent's tier default (`quick_think_llm` / `deep_think_llm`). Any agent not
listed keeps its tier default. Most useful with `llm_provider="openrouter"`,
where one API key (`OPENROUTER_API_KEY`) exposes every major lab's models
under namespaced IDs:

```python
config["llm_provider"] = "openrouter"
config["quick_think_llm"] = "openai/gpt-5.4-mini"
config["deep_think_llm"] = "openai/gpt-5.4"
config["agent_models"] = {
    "market_analyst":    "google/gemini-3-flash",
    "research_manager":  "anthropic/claude-opus-5",
    "portfolio_manager": "openai/gpt-5.4",
}
```

Valid keys: `market_analyst`, `sentiment_analyst`, `news_analyst`,
`fundamentals_analyst`, `bull_researcher`, `bear_researcher`,
`research_manager` (deep), `trader`, `aggressive_analyst`,
`conservative_analyst`, `neutral_analyst`, `portfolio_manager` (deep),
`reflector`, `signal_processor`.

Also settable from `.env` as JSON via `TRADINGAGENTS_AGENT_MODELS`.
Implementation: `TradingAgentsGraph._llm_for(agent_key, tier)` resolves and
caches one client per distinct model; `GraphSetup` receives the resolver
instead of two fixed LLM instances. Namespaced OpenRouter IDs inherit the
capability quirks of their bare counterparts (`capabilities.get_capabilities`
retries with the segment after the last `/`).

## Discovery tools (Alliela addition)

Three tools for the Idea Generation tier, usable before a ticker is
committed to. Implementations live in new modules
(`dataflows/yfinance_extra.py`, `dataflows/google_news.py`) rather than the
vendored yfinance files, registered in `dataflows/interface.py`, wrapped in
`agents/utils/discovery_tools.py`, and re-exported from `agent_utils`:

- `search_news(query, curr_date, look_back_days, limit)` — free-text
  theme/sector/event search. Default vendor `google_news` (keyless RSS,
  set as a `tool_vendors` default because the framework's vendor fallback
  only fires on rate-limit errors); `yfinance` (`yf.Search`) available via
  `config["tool_vendors"]["search_news"] = "yfinance"`.
- `get_ticker_snapshot(ticker)` — validates a candidate resolves and
  reports the liquidity/coverage screen: exchange, currency, price, market
  cap, average daily volume + value traded, 52-week range, sector.
  Unresolvable tickers return an explicit "unverified" notice.
- `get_earnings_calendar(ticker, curr_date)` — dated catalysts: upcoming +
  recent earnings dates with EPS estimates (yfinance).

## Run telemetry & output archive (requirement)

Binding requirement for the runtime (lands with the `api/` queue worker;
the product spec is the Run Ledger card in `web/pages/home.py` — see
`web/CLAUDE.md`): **every LLM call the framework makes must persist the
complete provider response — nothing summarised, nothing truncated.**
Per call, keyed by `run_id` + agent key + sequence:

- The full completion text (the node's entire output, not just the slice
  the pipeline consumes downstream).
- Every reasoning/thinking block the model exposes, verbatim.
- Tool calls with their full arguments and tool results.
- OpenRouter metadata: generation id, requested + resolved model,
  provider/variant actually served, finish reason, prompt/completion/
  reasoning token counts (native and normalised), cached-token counts,
  cost in USD, latency and throughput.
- Errors and the retry chain (what failed, what was retried, final state).
- The **raw response JSON** alongside the parsed fields, so nothing
  OpenRouter adds later is lost retroactively.

Per run, roll up: stage-level and run-level call counts, token totals
(in/out/reasoning), cost USD, wall-clock duration, outcome, and the list
of documents produced. This is what feeds the History knowledge store
and the site's Run Ledger; treat any pipeline change that would drop or
summarise a node's output as a regression.

## Knowledge-graph memory (requirement)

Binding requirement for the shared-state layer (the product spec is the
Fund Knowledge Graph modal — `KNOWLEDGE_GRAPH_INFO` in
`web/pages/home.py`; see `web/CLAUDE.md` § Shared Knowledge Layer):
the five knowledge stores (Mandate, Portfolio State, Theses, Lessons, Archive)
are **typed views over one property graph**, not five silos.

**Schema (minimum node and edge types).**

- Entity nodes: `Ticker`, `Sector`, `Factor`, `Event`, plus the fund's
  artefacts — `Thesis`, `Decision`, `Outcome`, `Lesson`, `Document`
  (every Document Trail box is a `Document` node).
- Seat identity: `Person` and `Duty` are first-class node types joined
  by `HOLDS` edges — one person can hold several duties (the PM's three
  duties are one `Person` with three `Duty` nodes). **Every `Decision`
  and `Outcome` carries a `PRODUCED_BY` edge to the `Duty` that made
  it**, so per-seat track records are graph queries, not archaeology.
- Lessons attach to every entity they generalise over (`ABOUT` edges to
  `Ticker` / `Sector` / `Factor` / `Event`), which is what makes
  retrieval associative rather than keyword-bound.

**Write regime.** Writes are curated — only the writers the flows
already draw: Execution's fills, the Research Manager's theses,
decision amendments, the Post-mortem's lessons, the Document Trails'
archive entries. Every write carries `run_id` provenance so any seat's
memory is reconstructable **as-of any run** — the Retrospective must be
able to replay exactly what an agent knew when it decided. No agent
writes free-form into its own memory: a self-written memory is a
self-edited prompt, which the Developer-Agent guardrail exists to
prevent.

**Read contract.** Per-agent memory is a *view*, not a store: the
subgraph within k hops of the seat's `Duty` node, filtered to lesson
and outcome edges, assembled at prompt-build time and exposed through
the shared tool interface (same access path as the PMS reads). Any
agent may query; reads are unrestricted.

**Store.** Neo4j is the natural engine (the Mac Mini already runs one
for the OpenData stack — the Alliela instance must be its own container
under the `alliela-trading` compose project, never a shared database).
Until the graph lands, the file/JSON-backed stores remain the interim
implementation; treat any new store code that couples one store's
internals to another as a regression against the one-graph model.

## Removed from the upstream vendoring

The following upstream files were intentionally deleted from this copy
because they don't contribute to "run the framework locally as a library":

- `cli/` — Rich/Typer terminal UI (removed in `39c0dd2`)
- `tests/test_api_key_env.py`, `test_crypto_asset_mode.py`,
  `test_ollama_base_url.py` — depended on `cli.utils` / `cli.models`
- `assets/` — README architecture diagrams (PNG)
- `README.md`, `CHANGELOG.md` — upstream documentation
- `Dockerfile`, `docker-compose.yml`, `.dockerignore` — Docker packaging
- `tests/` (whole folder, after the three cli-dependent files), `scripts/`,
  `test.py` — test infrastructure + ad-hoc scripts
- `.env.enterprise.example` — alternative env template (Azure etc.)
- `uv.lock`, `requirements.txt` — lockfile + redundant requirements pointer
- `rich`, `typer`, `questionary`, `tqdm` from `pyproject.toml` deps
- `[project.scripts]` console-script entry from `pyproject.toml`

**Upstream-merge implication.** Future `git subtree pull` from
`TauricResearch/TradingAgents` will reintroduce most of these. When pulling,
expect to re-delete them as part of the merge. The pipeline code under
`tradingagents/` is what we actually care about syncing.

## Licensing

The folder is **Apache 2.0**, inherited from the upstream fork — see
`LICENSE` (complete Apache-2.0 text) and `NOTICE` (Tauric Research
attribution, paper citation, and the summary of major modifications).
Upstream ships no NOTICE file of its own, so ours is the only one. Keep
`NOTICE`'s modification summary current when the pipeline shape changes
materially, and never remove either file — they must travel with every
distribution, including the public mirror.

## Updating the vendored upstream

This folder was added with:

```bash
git subtree add --prefix=trading-agents \
  https://github.com/TauricResearch/TradingAgents.git main --squash
```

To pull upstream changes later (preserving local edits):

```bash
git subtree pull --prefix=trading-agents \
  https://github.com/TauricResearch/TradingAgents.git main --squash
```

Resolve any merge conflicts as normal. Never push back to the TauricResearch fork.

## Notes

- All Alliela-specific configuration (env vars, secrets, deployment-specific
  code) should live in *our* additions; avoid editing upstream files in
  place when possible — it makes `git subtree pull` conflicts worse.
- `.env` is gitignored. To rotate or add an API key: edit
  `trading-agents/.env` then re-run.
