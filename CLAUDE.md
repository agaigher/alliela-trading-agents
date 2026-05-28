# `trading-agents/` CLAUDE guidance

This folder is the multi-agent LLM hedge-fund framework — the new Alliela product backend. **Vendored** from `TauricResearch/TradingAgents` via `git subtree --squash`, then customised for the Alliela deployment.

## Key facts

- Runtime: Mac Mini (production), to be exposed externally via Cloudflare tunnel once an HTTP wrapper exists.
- Origin: `https://github.com/TauricResearch/TradingAgents` (`main` branch).
- Stack: Python 3.12, LangGraph, multi-provider LLMs (OpenAI / Anthropic / Gemini / xAI / DeepSeek / Qwen / GLM / MiniMax), Docker.
- Entry: programmatic — import `from tradingagents.graph.trading_graph import TradingAgentsGraph` (a minimal usage example is at `trading-agents/main.py`). The upstream CLI (`cli/` directory + `tradingagents` console script) was **deleted** during vendoring; see "CLI removed" below.

## Mac Mini deployment

The repo is cloned at `~/Projects/alliela/` on the Mac Mini (Tailscale IP `100.91.207.5`, hostname `alliela`). odl lives at `~/Projects/odl/` on the same host and is **completely independent**.

**Isolation rule:** every `docker compose` command for trading-agents must pass `-p alliela-trading` so it does **not** collide with odl's `companies-graph` compose project. Resulting resource names are auto-prefixed: image `alliela-trading-tradingagents:latest`, network `alliela-trading_default`, volumes `alliela-trading_tradingagents_data` (and `alliela-trading_ollama_data` if the `ollama` profile is enabled).

### Initial build (already done)

```bash
ssh alliela@100.91.207.5
cd ~/Projects/alliela/trading-agents
cp -n .env.example .env       # empty placeholders; fill in real API keys before running
docker compose -p alliela-trading build tradingagents
```

### Smoke test

```bash
docker run --rm alliela-trading-tradingagents:latest
```

Runs the example driver at `trading-agents/main.py` (a one-shot analysis on
`NVDA`). With an empty `.env` this will fail at the first LLM call — that's
expected; it confirms the image is built and the framework imports cleanly.

### Run a one-off analysis (requires `.env` filled in)

```bash
docker compose -p alliela-trading run --rm tradingagents \
  python -c "
from tradingagents.graph.trading_graph import TradingAgentsGraph
from tradingagents.default_config import DEFAULT_CONFIG
ta = TradingAgentsGraph(config=DEFAULT_CONFIG)
_, decision = ta.propagate('AAPL', '2026-05-28')
print(decision)
"
```

### Updating from the host

```bash
ssh alliela@100.91.207.5
cd ~/Projects/alliela && git pull
cd trading-agents && docker compose -p alliela-trading build tradingagents
```

## CLI removed

The upstream `cli/` directory and three tests that depended on it
(`test_api_key_env.py`, `test_crypto_asset_mode.py`,
`test_ollama_base_url.py`) have been deleted from this vendored copy. The
plan is to drive the framework via a web API, not a terminal — so the
Rich/Typer/Questionary interactive layer carries no weight here. Removed
in detail:

- `cli/` (whole directory)
- `tests/test_{api_key_env,crypto_asset_mode,ollama_base_url}.py`
- `[project.scripts]` entry in `pyproject.toml` (the `tradingagents` console script)
- `rich`, `typer`, `questionary`, `tqdm` from `dependencies` in `pyproject.toml`
- `cli` from `[tool.setuptools.packages.find]` + the `cli/static/*` package-data line
- `Dockerfile` `ENTRYPOINT` changed from `tradingagents` to a default `python main.py`

**Upstream-merge implication.** This is vendored code (`git subtree --squash`
from `TauricResearch/TradingAgents`). A future `git subtree pull` *will*
reintroduce `cli/` and the three test files. When pulling, expect to
re-delete them as part of the merge — the rest of the pipeline code lives
under `tradingagents/` and is unaffected.

## Not yet wired up

- **HTTP/API wrapper.** Until a FastAPI shim exists, "exposed via Cloudflare" is aspirational. The next product step is to add a thin FastAPI service (e.g., `trading-agents/api/`) that wraps the orchestration entry points and listens on a host port (suggest `8002` — `8001` is taken by odl's `odl-graph-api`).
- **Cloudflare tunnel route.** Once the API exists, add an ingress entry in `~/.cloudflared/config.yml` mapping a public hostname (e.g., `api.alliela.com` or similar) to `http://localhost:8002`, then `cloudflared service restart`.
- **launchd job.** Once the API runs as a daemon, add a `com.alliela.trading.plist` in `~/Library/LaunchAgents/` to autorestart. Use the `com.odl.*` plists as templates.

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

- The upstream `LICENSE` is preserved here. Respect it for any redistribution.
- All Alliela-specific configuration (env vars, secrets, deployment-specific code) should live in *our* additions; avoid editing upstream files in place — it makes `git subtree pull` conflicts worse.
- Mac Mini operations are production. The Mac Mini *also* runs odl; never touch the `companies-graph` compose project, the `odl-*` containers, or `com.odl.*` launchd jobs from within this folder's workflow.
- `.env` on the Mac Mini holds the actual API keys and is gitignored. To rotate or add a key: SSH in, edit `~/Projects/alliela/trading-agents/.env`, then restart the container.
