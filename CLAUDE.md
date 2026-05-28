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

## Open issue: missing LICENSE

The upstream is **Apache 2.0**. The vendored snapshot does not currently
include a `LICENSE` file — either the original `git subtree add` predated
its addition upstream, or it was missed. For strict Apache 2.0 redistribution
compliance we should add a copy of the license text with attribution. Open
todo; not blocking for local development but should be resolved before this
repo goes fully public.

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
