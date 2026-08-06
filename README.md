# Alliela trading-agents

Multi-agent LLM hedge-fund framework — the backend of
[alliela.com](https://alliela.com). A pipeline of specialised LLM agents takes
an optional free-text mandate ("environment in Japan") through idea
generation, selection, deep research, adversarial debate, risk constraints,
and portfolio decision, producing an auditable research note at every step.
See the [whitepaper](https://alliela.com/whitepaper) for the full
architecture.

**This is the open-source part of the Alliela project** — published at
[agaigher/alliela-trading-agents](https://github.com/agaigher/alliela-trading-agents),
mirrored from the private monorepo where development happens. The
alliela.com web app and UI are separate, closed-source code and are not
included.

## Status

The public spec is ahead of the implementation. This codebase currently
implements the original TradingAgents pipeline shape (analysts → Bull/Bear
debate → Research Manager → trader → risk debate → Portfolio Manager) plus
multi-provider LLM and configuration work. The nine-tier architecture on
alliela.com — idea generation, selection committee, review-and-revise
loops, pre-mortem, binding risk constraints, funding, execution — is the
build target, with the site's sample-output documents as the output
contract.

## Credit — built on TradingAgents

This framework began as a fork of
[TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
(Apache-2.0):

> Xiao, Y., Sun, E., Luo, D., & Wang, W. (2024). *TradingAgents:
> Multi-Agents LLM Financial Trading Framework.*
> [arXiv:2412.20138](https://arxiv.org/abs/2412.20138).

The recognisable core — specialist analysts, the Bull/Bear researcher debate
judged by a Research Manager, the trader, the three-way risk debate, and the
portfolio-manager decision, orchestrated in LangGraph with a
quick-think/deep-think model split — originates there. The architecture has
since diverged substantially; see [NOTICE](NOTICE) for the modification
summary and [LICENSE](LICENSE) for the licence.

## Not investment advice

Outputs are research artefacts for studying multi-agent LLM reasoning. They
are not recommendations. LLMs hallucinate; verify cited sources before
drawing any conclusion.

## License

Apache License 2.0 — see [LICENSE](LICENSE). Original work © Tauric
Research; modifications © 2026 Allan Gaigher. See [NOTICE](NOTICE).
