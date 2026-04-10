# Phase 2 — Computer-Use Agents (CUA)

**Goal:** Explore agent-based interaction with tender websites as a fallback when
structured scraping fails.

## Files

| File | Responsibility |
|---|---|
| `action_space.py` | Discrete actions: `click`, `type`, `scroll`, `navigate`, `wait_for`, `download_link`, `finish` |
| `screenshot.py` | Capture + persist full-page screenshots between actions |
| `base_agent.py` | Abstract `BaseAgent` interface every agent must implement |
| `browser_agent.py` | Reference `PlaywrightCUA`: vision LLM + Playwright loop |
| `orchestrator.py` | Registry of available agents + entry point used by Phase 3 |

## The loop

```
1. Capture screenshot of current page
2. Send screenshot + history to vision LLM
3. LLM responds with one JSON action
4. Parse action → apply via Playwright
5. Repeat until `finish` or step budget exhausted
```

## Adding a new agent

Subclass `BaseAgent`, implement `run(url, max_steps) -> AgentRunOutcome`, then
register it in `orchestrator._build_registry`. Suggested next agents:

- `AnthropicCUA` — uses the official Anthropic computer-use tool
- `OpenAICUA` — uses OpenAI's computer-use API
- `BrowserUseAgent` — wraps the open-source `browser-use` library

Same harness, same metrics (`agent_runs` table) — directly comparable.

## Trigger an agent run from the UI

`/agents` page → paste a URL → "Run agent". Watch results in the runs table once
the worker picks it up.

## Trace replay

Every step writes its screenshot to `CUA_SCREENSHOT_DIR/{run_id}/step_NNN.png`. The
trace dict on each `AgentRun` row contains action history + screenshot paths so you
can replay a run later.
