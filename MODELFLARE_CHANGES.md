# Modelflare Edition changes

- `tradingagents/default_config.py`: Modelflare is the default provider and both thinking tiers use the strong `gpt-6-sol` model.
- `tradingagents/llm_clients/openai_client.py`, `api_key_env.py`: register the OpenAI-compatible Modelflare endpoint and `MODELFLARE_API_KEY` (with a read-only legacy alias). Modelflare forces `use_responses_api=False` because langchain-openai otherwise sends gpt-6 tool calls to `/v1/responses`, and that route rejects system messages. Chat completions accept system messages and function tools.
- `tradingagents/llm_clients/model_catalog.py`: Modelflare quick and deep presets are the strong IDs only (`gpt-6-sol`, `gpt-6-astra`, `claude-sonnet-5`, `claude-opus-5-5`, `gemini-3.1-pro-preview`, `grok-4.7`, plus Custom). Luna, Terra, Haiku, and Flash are not offered here. Other providers' lists are unchanged.
- `tradingagents/llm_clients/validators.py`: `modelflare` accepts any model id, so a custom gateway model does not warn.
- `tradingagents/llm_clients/modelflare.py`: one-token smoke call, plus `explain_api_error` for invalid keys (401), group/model access (403 or 503 with `model_not_found` or 分组), and balance (402 or quota/balance text). Friendly copy is used only when the base URL host contains `modelflare.dev`. A plain 403 is not described as an empty balance.
- `cli/selections.py`: interactive runs smoke after the prompts. A headless run that already has a Modelflare key keeps the built-in provider and models instead of prompting.
- `cli/run.py`: headless `--ticker` runs smoke once before the graph and exit 1 on failure. A missing key prints the signup link and does not prompt. OpenAI status errors from a Modelflare host print `explain_api_error` and exit 1. `openai` is imported only when an error is raised.
- `cli/prompts.py`: Modelflare is the first provider in the menu. An existing `MODELFLARE_API_KEY` (or legacy `MODELFLARE_KEY`) is reused and not prompted again.
- `.env.example`, `README.md`: one-key setup. The Modelflare header is wrapped in `<!-- MF-START -->` / `<!-- MF-END -->` with an `<!-- MF-SCREENSHOT -->` slot and no invented image. The upstream README below that header is unchanged.
- `docker-compose.yml`: pass `MODELFLARE_API_KEY` and `MODELFLARE_BASE_URL` (default `https://modelflare.dev/v1`) into the `tradingagents` service, and do not require a `.env` file, so `MODELFLARE_API_KEY=sk-xxx docker compose run --rm tradingagents` works.
- `.github/workflows/mf-upstream-sync.yml`: weekly merge (not rebase) of `https://github.com/TauricResearch/TradingAgents.git` using `secrets.MF_SYNC_TOKEN || github.token`. A clean merge opens a PR; a conflict opens an issue. Upstream workflow files are not deleted.
- `.github/workflows/mf-run.yml`: manual non-interactive analysis (`--ticker`, `--date`, `--analysts`, `--save`, `--no-show`) with `secrets.MODELFLARE_API_KEY`, and the report directory uploaded as an artifact.
- `tests/test_env_overrides.py`: built-in defaults are `llm_provider=modelflare` and `quick_think_llm=gpt-6-sol`.
- `tests/test_modelflare.py`: mocked smoke and error mapping for 401, 402, 403, 503 `model_not_found`, and non-Modelflare hosts (returns None). No network.

The agent graph, agent prompts, data vendors, other providers' model lists, and license are unchanged. A live analysis screenshot needs a real Modelflare key and is intentionally not fabricated.
