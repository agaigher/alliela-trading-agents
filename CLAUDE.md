# `trading-agents/` CLAUDE guidance

This folder is the multi-agent LLM hedge-fund framework. **Vendored** from `TauricResearch/TradingAgents` via `git subtree --squash`, then customised for the Alliela deployment.

## Key facts

- Runtime: Mac Mini (production), exposed externally via Cloudflare tunnel.
- Origin: `https://github.com/TauricResearch/TradingAgents` (`main` branch).
- Stack: Python, LangGraph, multi-provider LLMs (OpenAI / Anthropic / Gemini / etc.), Docker.
- Entry: `trading-agents/main.py` (CLI) and `trading-agents/tradingagents/` (library). See upstream `README.md` for architecture.

## Use this file when

- Adding Alliela-specific orchestration, endpoints, or storage on top of the upstream framework.
- Pulling in upstream updates (see "Updating from upstream" below).
- Deploying to or troubleshooting the Mac Mini runtime.

## Updating from upstream

This folder was added with:

```bash
git subtree add --prefix=trading-agents \
  https://github.com/TauricResearch/TradingAgents.git main --squash
```

To pull upstream changes later (preserving our local edits):

```bash
git subtree pull --prefix=trading-agents \
  https://github.com/TauricResearch/TradingAgents.git main --squash
```

Resolve any merge conflicts as normal. Never push back to the TauricResearch fork.

## Notes

- The upstream `LICENSE` is preserved at `trading-agents/LICENSE`. Respect it for any redistribution.
- All Alliela-specific configuration (env vars, secrets, deployment-specific code) should live in our additions; avoid editing upstream files in place when possible — it makes `git subtree pull` conflicts worse.
- Mac Mini operations are production. Follow the same safety guardrails as `companies-graph/`.
- Full runbook will live at `docs/trading-agents/runbook.md`.
