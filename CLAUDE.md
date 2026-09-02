# `trading-agents/` CLAUDE guidance

This folder is the multi-agent LLM hedge-fund framework — the Alliela
engine. Two layers live here:

- **`alliela/` — the Alliela pipeline core (phase 4, being built).**
  Plain Python, no LangGraph: explicit stage functions, Pydantic
  document models held to the site's 27 sample outputs, and a thin
  OpenRouter client (`alliela/llm.py`) that captures the complete raw
  response per the telemetry contract below. The engine emits captured
  calls + documents through a **sink protocol** (`alliela/sinks.py`)
  and ships only a file sink — Postgres persistence, queue consumption,
  and flow-version stamping live in the `api/` worker, never here (this
  is the open-source unit). Current coverage: Tiers 01–03 (Idea
  Generation — three desks + Head, one revision round; Selection
  Committee — three lens scorers + Chair, with the feasibility lens
  running on real Yahoo verification via `market.ticker_snapshot` —
  fantasy tickers and sub-floor liquidity are fatal on evidence;
  Analyst team — four specialists on real data packs (`price_pack`,
  `quote_summary` via the crumb-authenticated endpoint, news) + the
  Lead's audit-and-one-revision loop, reports forbidden from citing
  numbers outside their pack; Thesis Desk — Bull/Bear at three rounds
  on the frozen evidence, Research Manager judging into a Thesis with
  dated decidable kill criteria, Pre-mortem in prospective hindsight —
  all on the deep model with extended reasoning archived; conviction
  can be withdrawn — direction is an enum (long | short | pass) with
  nuance in a stance field; Pre-Trade Structuring — one deep call
  turning a non-pass Thesis into a Transaction Proposal with tranched
  entry, participation vs verified ADV, stop with basis, and the
  mandatory borrow-realism check; a pass ends the run at the desk;
  Risk panel — three lenses (Liquidity/Concentration/Drawdown) in a
  sequential debate against the real book, injected by the runner via
  ctx.book — the engine never reads a database; the Head of Risk signs
  typed binding RiskConstraints, veto available, extended reasoning;
  PM column — Decision (Opus, must address every constraint or
  escalate — one bounce-back round with the Head of Risk), Funding
  (cash first, then lowest-conviction trims), Instruction (binds all
  into the Dealing Instruction); Compliance gate — deterministic rule
  code in alliela/compliance.py, NO LLM, typed mandate limits checked
  against the book, N/E rules reported never skipped. **Those limits
  are DATA, not constants**: a `Restrictions` dataclass built from
  `RunContext.restrictions`, supplied per fund by the runner from the
  same mandate version whose prose the agents read, with
  `DEFAULT_RESTRICTIONS` as the house values and the fallback. Country
  caps are a list keyed by ticker suffix, generalising the old
  hardcoded ".T means Japan" proxy; a limit a mandate does not define
  is reported not-evaluable rather than silently passed. Constants
  would have meant enforcing the house fund's numbers against someone
  else's mandate. **Limits are hard or soft** (`limit_types`, plus a
  per-cap `type` on country caps): a hard breach fails the gate and
  returns the instruction to the PM; a soft breach is recorded and the
  run proceeds — comply-or-explain, for guidelines a market move can
  breach without anyone trading. `passed` means *no hard breach*;
  `soft_breaches(checks)` exposes the rest, every check carries
  `severity`, and the Compliance Record renders SOFT BREACH — never
  PASS — so repetition stays visible to the Retrospective. **Unlisted
  limits default to hard**, so a limit becomes advisory only by saying
  so; Execution —
  paper fills at verified snapshot prices, paced legs deferred
  honestly. The rollup returns fills + position context; the WORKER
  applies them to the positions table — the only PMS write, never the
  engine). **Origination is fully built, tiers 01–09.** The DAILY LOOP
  (stages/daily.py: intelligence duties → per-position verdicts →
  deep-think Portfolio Review → daily gate in compliance.check_daily →
  Execution) and the RETROSPECTIVE (stages/retrospective.py:
  Scorekeeper → Attribution → 3-lens Process Audit reading actual
  prompts + archived traces → Head of PR → Improvement Backlog) are
  built — all three flows now execute for real.
  Every structured call routes through alliela/structured.py
  (ask_validated: one archived JSON-repair retry).
  Build decisions are recorded in `docs/backend-plan.md` § phase 4.
- **`tradingagents/` — the vendored TauricResearch framework**, kept as
  the data/tools library (dataflows, discovery tools). Its old
  LangGraph pipeline is NOT being evolved into the Alliela pipeline and
  will be trimmed further as the core takes over. Vendored via
  `git subtree --squash`; details below.

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

## Per-fund agent overrides (`alliela/overrides.py`, Aug 2026)

Distinct from the vendored framework's `agent_models` above: that is
config for the whole process, this is **one fund's owner editing their
own desks** from the portal. The two do not interact.

`pipeline_spec()` returns **every flow the engine runs** —
`{flows: [origination, management], models}` — so the portal draws them
from the same source. Origination is derived from its stage constants;
the management flow (`daily.py`) is authored in `DAILY_NODES` because
its duties are not declared as a constant, but its **edges are read off
what each duty is actually handed** — the Portfolio Review is given all
four duty reports as well as the verdicts, so it has five inputs, not
one. `execution` appears in both flows on purpose: it is one seat both
flows hand an instruction to, so an override on it applies wherever it
runs. Duplicating it under a second id would promise a distinction the
engine does not make. **`post-mortem` is deliberately absent** — the
marketing page carries a template for it, but no such agent exists in
the engine, and a graph that claims to be derived from the code must
not show one.

`RunContext.agent_overrides` maps a **graph_spec node id** to
`{model, prompt}`. It is applied in exactly one place —
`ask_validated`, which every stage already funnels through — so a new
stage inherits the behaviour by construction and no stage has to know
overrides exist. Every call site passes `node=<graph_spec id>`, checked
against the spec both ways (no unknown ids, no agent without a hook).

**The editor is prefilled with the agent's real prompt**, which is why
`alliela/prompts.py` exists: `default_prompt(node_id)` returns the
exact system prompt that agent runs on. An empty box invites an owner
to replace a careful brief with one sentence and silently lose every
rule the desk had.

To make that possible, all 20 inline system prompts were **lifted to
module-level functions** (`*_system_prompt`) — 14 in origination, 6 in
the daily loop — following the convention `thesis.manager_system_prompt`
already set for the Prompt Auditor. Both lifts were done by moving the
expression source, never retyping it, and verified by evaluating the
pre-refactor expressions and diffing: **all 20 byte-identical**. The
daily loop's `honesty` local became the module constant `HONESTY` for
the same reason — a prompt that only exists inside a function cannot be
handed out. Keep prompts there — a prompt the engine can
hand out is a prompt something else can read.

What the owner may change:

- **`model`** — from `MODEL_CHOICES` only. A free-text model field is
  an unbounded bill: one confident string and a fund runs 60-odd calls
  against the dearest endpoint on OpenRouter. A model no longer in the
  list is **ignored, not raised** — a retired model must not brick
  every future run of a fund that once selected it.
- **`prompt`** — the whole system prompt, contract included. Run-time
  values stay as `{fund_name}` / `{mandate}` / `{tip}` and are
  substituted at run start (`overrides._fill`, plain `str.replace` —
  these prompts are full of JSON braces). **Storing the mandate text
  instead of the token would freeze a copy of it**, so an owner editing
  their mandate later would leave the agent reading the old one.
  If an owner deletes the schema, the engine puts one back: every JSON
  Schema dump contains `"properties"`, so its absence is the test.

**Secondary duties** (`SECONDARY_DUTIES`): the Head of Idea Generation
also reviews the desk books, and the Head of Risk also answers the PM's
escalation — both on *different* prompts from the one the owner edits.
Those call sites pass `override_prompt=False`, so they take the model
override but keep their own instructions. Putting a compile prompt on a
review call would be a silent mis-instruction.

What is deliberately **not** overridable:

- **The Compliance gate** has no model — it is rule code reading the
  mandate's typed limits. The api refuses a prompt for it. The one
  stage that can stop a trade must not be persuadable.
- **The mandate.** Instructions are how an agent works, not what it is
  permitted to do; nothing written here reaches the gate.
- **Tools.** The engine hands agents prepared context packs and the
  agents call nothing themselves (see "Internet tools" below). A tool
  picker would store a preference nothing reads, so the portal says so
  instead of showing one.

Overrides are read **once** when the worker starts a run and frozen on
the context, for the same reason the mandate version is pinned: editing
an agent must not change the rules half way through a run in flight.

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

## Internet tools (decision, Aug 2026)

When agents get open-web search (first consumers: the Retrospective's
Win/Failure Analysis duties; spec `PERF_WEB_TOOLS` in
`web/pages/home.py`), the providers are the **Google Search API**
(primary) with the **DuckDuckGo API** as fallback — not scraping, not
a headless browser. Same context-pack-or-tool pattern as the existing
market helpers in `alliela/market.py`; keys live in the deployment
`.env`, never in this open-source unit.

## Evidence and research volume (decided 2 Sep 2026)

**The finding.** Every real thesis the desk has judged since Tier 04
went live — SIE.DE ×2, ENR.DE, ETN, NXPI, across two funds and four
mandates — ended `pass`, and none of them was a rejection. All five are
deferrals ("conviction is withheld, not killed", "re-underwrite as long
only if…"). The Bear won each time on the same ground: the load-bearing
numbers (segment revenue, order-book, filing disclosures, transcript
commentary) were flagged unverified in the fund's own reports. Three
structural causes, none of them the bar:

1. The data layer (`alliela/market.py`) is Yahoo chart + Yahoo
   quoteSummary + Google News RSS **titles** — no article text, no
   filings, no segments. The analyst rule "if the pack lacks it, put it
   in `coverage_gaps`" then manufactures the gap the Bear cites.
2. The desk rule "a claim without a citation is conceded" makes a
   coverage gap unanswerable — the rebutting fact is what the pack
   omits.
3. The Bear speaks last (`stages/thesis.py`: Bull opens, Bear closes
   turn 6, Manager judges). And the Manager prompt folds "deferred" into
   `pass`, so "yes, after Q3 confirms X" ends the run like "bad idea".

**The bar stays.** No change to the Manager's standard of evidence; a
position is not bought for the sake of buying. What changes is the
evidence supply, the volume of research per run, and the verdict
vocabulary. Three phases, each its own flow version, in this order.

### Phase A — bounded tool-calling for the Analyst team

- **Who:** Tier 03 analysts only. The Thesis Desk, PM and everything
  downstream keep reading a **frozen pack** — the debate adds no data.
- **How:** OpenRouter tool-calling (`tools` in the request, tool
  results fed back) inside `ask_validated`, so overrides and telemetry
  inherit it. Cap **6 tool calls per analyst per pass**; a call over the
  cap is refused with a message, not silently dropped.
- **Logged, twice.** Every call + args + result lands on the
  `CapturedCall` (new `tools` field → the already-provisioned
  `run_calls.tools` column — the telemetry requirement below has
  demanded this since day one). And each analyst's fetched evidence is
  written as its own document (`{key}-evidence`) before Tier 04 starts:
  that document is the frozen pack, and the Retrospective audits it.
- **Tool failures are data.** A tool that cannot answer returns
  `{"status": "unavailable", "why": …}`; the analyst records the gap.
  Never a fabricated result, never a silent empty.
- **Free tool set (keyless, this phase):**
  - `sec_filings` — EDGAR submissions index for a ticker (forms, dates,
    accession numbers).
  - `sec_financials` — XBRL companyfacts: dated, as-reported values per
    concept, segment dimensions where the filer tagged them.
  - `sec_filing_section` — one item of a 10-K/10-Q/20-F (MD&A, segment
    note, risk factors, guidance), trimmed to a token budget.
  - `sec_fulltext_search` — EDGAR full-text search over filings, dated.
  - `article_text` — resolve a Google News link and extract the body.
  - `news_search` — the existing RSS search, wider limit, dated.
  - `price_history` / `realized_vol` — Yahoo chart at longer ranges,
    realized volatility over a named window (the Risk panel's missing
    input).
  - `options_iv` — Yahoo options chain, ATM implied vol; US-listed only.
- **Honest coverage limit.** EDGAR covers US filers and foreign private
  issuers (20-F/6-K). A German or Japanese primary listing gets article
  text and price tools only; its segment gap stays a gap. That is the
  case for paid providers (below) — not a reason to loosen the desk.
- **Exit test:** one real run whose Thesis cites a filing-sourced
  number no pack-only run could have produced, with the evidence
  document showing the fetch.

**Built 2 Sep 2026, local dry run passed; the real run is still to
go.** What shipped, and where the spec above bent to reality:

- `alliela/tools.py` — the registry (spec + impl + per-lens
  `TOOLSETS`), `execute()` that turns every failure into a status. The
  loop lives in `ask_validated` (`structured.py`): each round trip is
  its own captured call, recorded *after* its tools ran so the archive
  row carries them; the seventh call in a pass is refused with a
  message that tells the analyst to write with what it has. `llm.py`
  sends `tools`, captures `tool_calls`, and `CapturedCall.tools` holds
  the executed trail → `run_calls.tools` (the worker now writes the
  column 002 provisioned) and `FileSink`.
- **No EDGAR full-text search.** `efts.sec.gov` answers 403 to every
  non-browser client whatever the headers. Dropped rather than shipped
  broken — a tool that always fails teaches the analyst to stop
  calling tools. Eight tools, not nine.
- **News links come from Yahoo Finance's search**, which returns the
  publisher URL; GDELT is best-effort with a per-run circuit breaker
  (it times out from this network); Google News RSS stays for title
  breadth. Yahoo article pages answer a **consent wall** from the UK,
  which `article_text` reports as `blocked` — it used to return the
  cookie policy as `ok`, which is worse than nothing.
- `sec_financials` follows **concept aliases** (`Revenues` →
  `RevenueFromContractWithCustomerExcludingAssessedTax` under ASC 606)
  and flags a concept as `stale` when its newest value is over ~18
  months old, with the filer's nearest live tags. Consolidated facts
  only; segment splits come from `sec_filing_section("segment")`,
  which strips the inline-XBRL `<ix:header>` (otherwise the first
  "backlog" hit is a member name) and falls back to approximate
  multi-word matching, labelled as such.
- **`CapturedCall.json_text` tolerates prose around the JSON.** A
  model that has just used tools narrates before the document; on the
  dry run that cost a repair call per report (8 of 35 calls). Now the
  fenced block or outermost object is taken first.
- **Dry-run economics** (`scripts/dry_run_analysts.py`, ETN, quick
  model): 35 calls, 40 tool calls, $0.43, ~4 min for Tier 03 alone —
  against 9 calls before. The Fundamentals Analyst cited the Q2 2026
  10-Q segment note ($8.007B Electrical Americas backlog) and the debt
  step-up ($9.895B → $21.33B) — numbers no pack-only run has ever had.
  Coverage gaps stayed honest where the free tools end: borrow cost,
  transcripts, segment operating margin Eaton does not tag.
- `scripts/test_tool_loop.py` — the loop against a scripted fake
  model, no network: execution, refusal, budget, evidence, JSON.
- **Deployed 2 Sep 2026** — worker rebuilt on the mini at `a0d886f`
  (no migration; the column existed), public mirror synced. Registered
  as **flow v6** ("Evidence package") with v5's `pipeline_spec` copied
  across: the graph's topology did not change — tools are not nodes —
  and a version without a spec row would leave the portal drawing a
  plain strip. Exit test: RUN-0154, a free scan on Global Equities
  Tactical Fund, enqueued by SQL insert (no credit hold; `settle`
  debits the metered cost at the end regardless). The Retrospective's
  Prompt Auditor sees the tool rules because they live in
  `analyst_system_prompt`, module-level.

### Phase B — research volume

- **Bull closes.** Three rounds, then a Bull closing rebuttal (turn 7).
  The Manager prompt gains one rule: an unfilled coverage gap is a cost
  to the thesis, not a verdict on its own — the verdict must weigh what
  the evidence does show.
- **News depth.** Idea Generation 8 → 20 headlines per query. Analyst
  news queries 2 → 5 (name+ticker, name+catalyst, competitors/sector,
  regulator/policy, guidance/outlook), top bodies via `article_text`.
- **Two revision passes.** The Lead audits twice; the second pass is
  where tool calls chase the first audit's gaps. +4 quick-model calls.
- **Second candidate.** Selection promotes its top two; both run Tiers
  03–04. If both come back non-pass, Structuring takes the higher
  conviction and the other becomes a `defer` (Phase C). If one passes,
  the other proceeds. Doubles the cost of Tiers 03–04.

### Phase C — `defer` as a first-class verdict

- `Thesis.direction ∈ {long, short, pass, defer}`. `pass` = the idea is
  wrong. `defer` = right idea, evidence not yet in hand — and it must
  carry ≥1 dated, decidable re-entry criterion.
- A deferred thesis persists to a `watchlist` table (fund, ticker, run,
  criteria, review-by). The daily loop checks whether a criterion has
  fired; an origination may pick a fired name up as its tip. A `defer`
  never opens a position — it arms one.
- **Shadow-tracked against the benchmark.** Every `defer` *and* every
  `pass` is marked daily from the verdict date at the price then, in the
  thesis's direction, against the fund's benchmark — a paper record of
  the positions not taken. Never counted in NAV. The Retrospective reads
  it: a watchlist that keeps beating the benchmark says the desk is too
  slow; passes that would have lost say it was right to refuse. The
  desk's misses and its correct refusals both become measurable.
- **Portal:** the fund page shows the watchlist beside the book, each
  entry with its shadow return vs benchmark since the verdict.

### Paid data — roadmap, not now

Paid providers (segment financials, transcripts, European/Japanese
coverage — FMP/EODHD class) are a future portal option **charged
separately**: an owner chooses free tools or paid tools per fund, and
paid fetches settle through the same credit ledger as model calls. This
also reverses the P3 "no tool picker" refusal — once agents call tools,
a picker stores something the engine reads. Keys stay in the
deployment `.env`, never in this open-source unit.

### Economics

Today: ≈ $1.00, 29 calls, ~15 min, 18 documents per origination.
Projected after A+B: **$2.5–3.5, 25–35 min** — tool calls are free HTTP
but lengthen prompts; the second candidate doubles the deep tiers.
`credits.estimate_micros` learns from history, so the first runs on a
new flow version **under-hold** by design; settlement bills the actual.
Make the estimate flow-version-aware (average over the current version,
fall back to all) before Phase B ships to owners.

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
- The **flow version** (registered pipeline version + engine git commit)
  the run executed under — one version per run, inherited by every call
  and document. The Retrospective evaluates each decision against the
  version that made it, so an unstamped call is an unattributable one
  (see `docs/backend-plan.md` § "Flow versioning").

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

## Node lifecycle — `sink.on_node` (Aug 2026)

The portal lights up each agent on its graph while a run is going. That
needs something the archive cannot supply: `run_calls` is written when a
call **returns**, so an agent thinking for ninety seconds is invisible
for exactly the ninety seconds a watcher cares about.

So `ask_validated` emits `sink.on_node(node, stage, agent, state)` either
side of the call — `"running"` before, `"done"` after. It lives there for
the same reason the overrides hook does: **every stage funnels through
that one function**, so one edit covers the pipeline instead of ten.

- **Optional at every step.** No `node` id, no sink, or a sink predating
  the protocol — all skipped, and an `on_node` that raises is caught and
  logged. A run that finishes with a gap in its progress bar beats a
  paid run that dies reporting one.
- **Repair is not a second agent.** A malformed-JSON repair call stays
  inside the same agent's turn: `done` fires once, after the repair
  validates.
- **The Compliance gate is rule code** and never reaches
  `ask_validated`, so `pipeline.py` calls `note_node()` around it
  directly — otherwise the one deterministic seat would be the one that
  never lights up.
- **Documents carry their node id** in meta (`{"agent": …, "node": …}`),
  which is how the portal attaches "here is what this agent wrote" to
  the right seat. The ids are `graph_spec` node ids; a typo there is a
  document that silently never appears, so they are worth checking
  against `pipeline_spec()` when adding a stage.
- `FileSink` writes `nodes.jsonl`, flushed per event — a buffered
  progress log is one you can only read once you no longer need it.

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
