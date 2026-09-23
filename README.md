# Wargs

An autonomous, hypothesis-driven investigation engine.

Given a question about a real-world phenomenon, Wargs:

1. generates competing hypotheses,
2. identifies what evidence would distinguish them,
3. autonomously researches the highest-value evidence,
4. updates the hypotheses,
5. actively searches for contradictory evidence,
6. repeats until the evidence is sufficient,
7. produces an uncertainty-aware conclusion.

The central idea: **Wargs does not optimize for producing a confident answer. It optimizes for finding explanations that survive attempts to disprove them.**

The name is a nod to *winning arguments*: hypotheses compete, and only the
ones that withstand contradictory evidence win.

See [architecture.md](architecture.md) for the architectural reference (as
implemented), [docs/investigation-flow.md](docs/investigation-flow.md) for the
investigation flow, and [docs/aspirations.md](docs/aspirations.md) for the
not-yet-implemented design ideas.

## Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

## Setup

```bash
uv sync
```

Create a `.env` file in the project root with:

```bash
OPENAI_API_KEY=<your-key>
OPENAI_BASE_URL=<your-openai-compatible-endpoint>  # e.g. https://api.openai.com/v1/
WG_TAVILY_API_KEY=<your-tavily-key>
```

`OPENAI_API_KEY` / `OPENAI_BASE_URL` point to any OpenAI-compatible chat API
used for the agent model calls. `WG_TAVILY_API_KEY` is used for web research
via [Tavily](https://tavily.com). Environment variables prefixed with `WG_`
are loaded by the `SecretsManager`.

## Usage

```bash
uv run app.py -q "Your investigation question here"
```

Omit `-q` to run one of the built-in example questions.

## Project structure

```
app.py                        # CLI entry point
src/
  config.py                   # Config + SecretsManager (WG_* env vars)
  core/
    model.py                  # OpenAI-compatible model client
    agent/                    # Agent loop, prompts, schemas
    orchestrator/             # Investigation orchestrator
  tools/                      # Tool executor and evidence store
```

## License

[MIT](LICENSE)
