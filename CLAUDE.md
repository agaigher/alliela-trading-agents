# `trading-agents/` CLAUDE guidance

This folder is the multi-agent LLM hedge-fund framework — the new Alliela product backend. **Vendored** from `TauricResearch/TradingAgents` via `git subtree --squash`, then customised for the Alliela deployment.

## Key facts

- Runtime: Mac Mini (production), to be exposed externally via Cloudflare tunnel once an HTTP wrapper exists.
- Origin: `https://github.com/TauricResearch/TradingAgents` (`main` branch).
- Stack: Python 3.12, LangGraph, multi-provider LLMs (OpenAI / Anthropic / Gemini / xAI / DeepSeek / Qwen / GLM / MiniMax), Docker.
- Entry: upstream `main.py` (CLI via the `tradingagents` script). Library code under `trading-agents/tradingagents/`. See upstream `README.md` for architecture.

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
docker run --rm alliela-trading-tradingagents:latest --help
```

Should print the `tradingagents` CLI usage.

### Run a session (interactive, requires `.env` filled in)

```bash
docker compose -p alliela-trading run --rm tradingagents
```

### Updating from the host

```bash
ssh alliela@100.91.207.5
cd ~/Projects/alliela && git pull
cd trading-agents && docker compose -p alliela-trading build tradingagents
```

## Not yet wired up

- **HTTP/API wrapper.** Upstream is a CLI; there is no FastAPI shim. Until one exists, "exposed via Cloudflare" is aspirational. The next product step is to add a thin FastAPI service (e.g., `trading-agents/api/`) that wraps the orchestration entry points and listens on a host port (suggest `8002` — `8001` is taken by odl's `odl-graph-api`).
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
