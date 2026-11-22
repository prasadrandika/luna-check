# luna-check

Find the code that uses AI models and API features that are retired or about to shut down, before your users find it for you.

luna-check started with OpenAI's **Jan 14, 2027** shutdown of GPT-4o, GPT-4o mini, GPT-4.1 and GPT-4.1 mini (hence the name: `gpt-6-luna` is the replacement). Since 0.4.0 it also covers these platforms, using each one's official deprecation page:

| Platform | Official page | Upcoming examples |
|---|---|---|
| OpenAI API | [Deprecations](https://developers.openai.com/api/docs/deprecations) | `gpt-5`, `o3` (Dec 11, 2026); `gpt-4o`, `gpt-4.1` (Jan 14, 2027) |
| Claude API (Anthropic) | [Model deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations) | `claude-sonnet-4-5-20250929` (Nov 30, 2026) |
| Gemini API | [Gemini deprecations](https://ai.google.dev/gemini-api/docs/deprecations) | `gemini-2.5-pro`, `gemini-2.5-flash` are routed to newer models from Dec 1, 2026 |
| Vertex AI | [Model versions and lifecycle](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/model-versions) | `gemini-2.5-pro`, `gemini-2.5-flash` retired Oct 20, 2026 |
| Azure OpenAI | [Model retirement schedule](https://learn.microsoft.com/en-us/azure/foundry/openai/concepts/model-retirement-schedule) | `gpt-4o` 2024-05-13 (Jan 14, 2027); other `gpt-4o`, `gpt-4o-mini`, `gpt-4.1` versions (Apr 14, 2027) |
| Amazon Bedrock | [Model lifecycle](https://docs.aws.amazon.com/bedrock/latest/userguide/model-lifecycle-legacy.html) | `anthropic.claude-sonnet-4-5-20250929-v1:0` (Apr 8, 2027) |

| Rule | What it finds | Source |
|---|---|---|
| **LC001** | A model ID that is retired or has a shutdown date, in code or as the value of a model setting in a config file. The dates, replacements and source links come from [`models.json`](src/luna_check/data/models.json), built from the pages above. | The page that lists the model |
| **LC002** | A `tiktoken.encoding_for_model()` call. tiktoken has no entry for `gpt-6-luna`, so after the switch the call raises `KeyError`. This was checked with tiktoken 0.7.0 and 0.14.0. | [tiktoken/model.py](https://github.com/openai/tiktoken/blob/main/tiktoken/model.py) |
| **LC003** | A request that sets `temperature`, `top_p`, `top_logprobs` or `logprobs` without setting reasoning effort to `"none"`. OpenAI's guide says to remove these when reasoning effort is not `none`, and gpt-6-luna defaults to `medium`. | [Using GPT-6: migration quickstart](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart), [gpt-6-luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| **LC004** | Function tools sent to `/chat/completions` without `reasoning_effort`. On Chat Completions, gpt-6-luna supports function calling only with `reasoning_effort` set to `none`. | [gpt-6-luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| **LC005** | `temperature`, `top_p` or `top_k` in a Claude Messages request. API version `2026-10-21` (used by the Python SDK 2.0.0 and TypeScript SDK 1.0.0) returns a 400 error for them on every model. Older API versions already reject non-default values on Claude 4.7 and later. | [Anthropic: API parameter deprecations](https://platform.claude.com/docs/en/about-claude/model-deprecations), [Migrating to 2026-10-21](https://platform.claude.com/docs/en/api/migration-2026-10-21) |
| **LC006** | A retired or retiring OpenAI feature: the Assistants API (shut down Aug 26, 2026), reusable prompt objects `pmpt_...` (Nov 30, 2026), Evals API writes (read-only from Nov 30, 2026), `/v1/audio/translations` (Feb 26, 2027), the Videos API, and the `OpenAI-Beta: realtime=v1` header. | [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations) |

LC002 to LC004 are about the move to `gpt-6-luna`, so they only look at files that name one of the four Jan 14 models or `gpt-6-luna`.

Each finding in the report includes its source link.

## Install

```bash
pip install git+https://github.com/prasadrandika/luna-check@v0.4.2
```

It needs Python 3.9 or newer and Git, has no dependencies, and works on Windows, macOS and Linux. It is not on PyPI yet.

## Use

```bash
luna-check path/to/project
```

```
luna-check 0.4.0: scanned 3 file(s) in path/to/project

app.py
  line 43  HIGH  LC002  tiktoken.encoding_for_model() raises KeyError for gpt-6-luna
      Called with "gpt-4o-mini". tiktoken has no entry for "gpt-6-luna", so after the switch this raises KeyError (checked with tiktoken 0.7.0 and 0.14.0).
      Fix: Catch the error and fall back to get_encoding("o200k_base"), the encoding tiktoken uses for gpt-4o, gpt-4o-mini, gpt-4.1 and gpt-4.1-mini.
      Source: https://github.com/openai/tiktoken/blob/main/tiktoken/model.py
  line 73  HIGH  LC001  Model is retired or scheduled to shut down
      "gpt-4o-mini" points to the dated snapshot(s) gpt-4o-mini-2024-07-18, which shut down on Jan 14, 2027. Replace it with "gpt-6-luna".
      Fix: Use "gpt-6-luna" (or read the model name from config).
      Source: https://developers.openai.com/api/docs/deprecations

Found 2 high, 0 low in 1 file(s).
```

| Option | Meaning |
|---|---|
| `--include-tests` | Also scan test files. They are skipped by default. |
| `--format json` | Machine-readable output. |
| `--exit-zero` | Always exit 0. |

**Exit codes:** `1` if any HIGH finding was found, `0` if not, and `2` if the path doesn't exist. LOW findings never fail the run.

## GitHub Action

```yaml
- uses: actions/checkout@v5
- uses: prasadrandika/luna-check@v0.4.2
  with:
    path: .          # folder to scan
    fail: true       # false = report only, never fail the job
```

## How it avoids false positives

- It scans code in `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs` and `.go` files. It does not scan Markdown.
- **Config files** (`.env`, `.env.*`, `.yaml`, `.yml`, `.json`, `.toml`) are checked for LC001 only. A model ID counts only when it is the value of a model-like key: `model`, `models`, `model_name`, `model_id`, `default_model`, `llm_model`, `OPENAI_MODEL`, `defaultModel` and so on. Docker Compose `- OPENAI_MODEL=...` and Kubernetes `name:`/`value:` env entries count too. Example, sample and template configs such as `.env.example` are LOW. Lockfiles and package files (`package.json`, `package-lock.json`, `pnpm-lock.yaml`, `pyproject.toml`, `Cargo.toml`, `*.lock` and similar) are skipped, and so are JSON objects that also hold a price or cost and config files in folders of recorded data (`testing/`, `__live__/`, `__snapshots__/`, `cassettes/`, `recordings/`).
- **Comments and Python docstrings are ignored.** A small lexer removes them before any check runs.
- **Tests are skipped:** `tests/`, `test/`, `__tests__/`, `testdata/`, `test_*.py`, `*_test.py`, `*_test.go`, `*.test.ts`, `*.spec.js` and similar.
- **Price and lookup tables are skipped.** That covers a model name used as a mapping key (`{"gpt-4o": 2.5}`) and any line that mentions price, cost or per-1M.
- **Prose is skipped.** A string that contains spaces, such as a log message or a prompt, is not treated as a model setting.
- **Seed, demo, mock, fixture and sample files** are reported as LOW.
- **Model catalogs are LOW.** A retiring ID inside a list or map that holds 4 or more different model names, such as a list of known or allowed models, is reported as LOW. A model ID used on its own, as a default or in a request, stays HIGH, and so does a short fallback list.
- Folders like `node_modules`, `vendor`, `.venv`, `dist` and `build` are skipped.
- To silence one line, add a comment containing `luna-check: ignore` on that line.

### Which platform's date?

Some model IDs are on two platforms with different dates. luna-check looks at the file:

- **Azure OpenAI** (`AzureOpenAI`, `azure_endpoint`, `.openai.azure.com`, `AZURE_OPENAI_*`): only Azure's schedule is used, and a bare name like `gpt-4o` lists the date of each Azure version, because Azure code names a deployment, not a model version. Models that Azure's schedule page doesn't list are not reported in Azure files.
- **Vertex AI** (`vertexai=True`, `vertexai`, `aiplatform`, `ChatVertexAI`, `GOOGLE_GENAI_USE_VERTEXAI`) vs the **Gemini API** (`GEMINI_API_KEY`, `google.generativeai`, `ChatGoogleGenerativeAI`): the platform the file uses wins. If the file shows neither, the Gemini API date is reported with a note about Vertex AI.
- **Amazon Bedrock** IDs (`anthropic.claude-...-v1:0`, also with a `us.`/`eu.`/`global.` prefix) have their own dates, which differ by Region. The finding lists each Region group.
- A model that is deprecated but has no shutdown date yet is LOW. A Gemini model that is already being routed to a newer model is LOW too: requests still work, on the newer model.

A model name used as a prefix or substring test, as in `name.startswith("gpt-4")`, is not reported.

LC003 reports a sampling setting only when reasoning effort is missing or set to something other than `"none"`. If reasoning effort comes from a variable, luna-check can't tell its value, so it reports nothing.

## Changes

**0.4.2**
- Fix: Azure OpenAI replacements no longer include the page's footnote markers (`gpt-5.6-sol^4^` is now `gpt-5.6-sol`). This affected 7 o-series entries in 0.4.0 and 0.4.1.

**0.4.1**
- Model data refreshed from the official pages on Nov 22, 2026 (the first weekly refresh): Vertex AI moved `gemini-3.6-flash` to Jan 28, 2027 and lists `gemini-4-hydrogen` as the replacement for it and `gemini-3.7-flash`; seven Azure OpenAI o-series versions are now retired.
- New `refresh-models` workflow keeps the data current (see "How the model data stays current").

**0.4.0**
- LC001 covers OpenAI, Anthropic, the Gemini API, Vertex AI, Azure OpenAI and Amazon Bedrock. It reports every retired or retiring model ID listed on their official pages (not only the four Jan 14, 2027 OpenAI models), with that page's date, replacement and link.
- The data is in `src/luna_check/data/models.json`, generated by `scripts/build_models.py` from the official pages.
- New rule LC005: Claude `temperature`, `top_p` and `top_k`.
- New rule LC006: retired or retiring OpenAI features and endpoints.
- A list of records with one model name each (`[["gpt-5", 1], ...]`) counts as a model catalog (LOW).
- The LC001 title is now "Model is retired or scheduled to shut down".

**0.3.0**
- Config files are scanned: `.env`, `.env.example`, YAML, JSON and TOML. LC001 reports a retiring model ID when it is the value of a model-like key. Example configs are LOW.
- A retiring model ID in a list or map of 4 or more model names (a catalog or allow-list) is now LOW, not HIGH.
- Short LOW lines in the report now say why they are LOW, and the JSON report has a `low_reason` field.

**0.2.1**
- Findings now describe OpenAI's rules in luna-check's own words and link the source. They no longer quote OpenAI's pages.
- The footer line now reads "Need help migrating? prasadrandika.github.io".

**0.2.0**
- LC003 runs by default and is HIGH. `--strict` and the Action's `strict` input still work but have no effect.

**About LC003's source.** OpenAI's "Using GPT-6" guide covers gpt-6-luna. It says to drop the sampling parameters only when reasoning effort is not `none`, so LC003 skips requests that set it to `"none"`. The newer "Using GPT-6.2" guide at `/guides/latest-model` says to drop them with no effort condition, but it is written for gpt-6.2 models. LC003 follows the gpt-6-luna guidance.

## Limits

luna-check reads code. It does not run it. It won't see a model name that is set only at deploy time, such as a secret or a CI variable, and it can't follow a request built in a different file from where it is sent. A clean report means none of these known patterns were found. It does not prove the migration will work, so test your app against the replacement model too.

The model data is a copy of the providers' pages from the date in `models.json` (`checked`). New retirements are added in new releases.

### How the model data stays current

Every Monday the `refresh-models` workflow runs `scripts/refresh_models.py`. It rebuilds `models.json` from the official pages and, if anything changed, opens a pull request that lists each added, changed and removed entry with its source link and the test result. If a page can't be read the usual way (a parser error, no rows, or far fewer rows than before), it opens an issue instead and leaves the data alone. A person reviews every change before it is merged and released.

## Tested on real migrations

Five real projects were migrated off `gpt-4o-mini`: Basic-Rag, youtube_transcription_api, dsl, Nasiko and WeClaw. The tests check two things: luna-check finds every problem each migration fixed in the "before" version, and it reports nothing in the "after" version. Files from the three projects with an open-source license are stored in `tests/fixtures/real/` with their licenses. Small example files for each platform are in `tests/fixtures/providers/`. One unchanged file from [grafana/ai-sdk](https://github.com/grafana/ai-sdk) (Apache-2.0), its list of known OpenAI model IDs, tests that model catalogs are reported as LOW. The other two projects have no license, so their files are downloaded at pinned commits when the tests run.

## Further reading

- [Migrating from GPT-4.x to GPT-6 Luna](https://help.openai.com/en/articles/20001600-migrating-from-gpt-4x-to-gpt-6-luna) (OpenAI Help Center)

## License

MIT

---

Need help migrating? [github.com/prasadrandika](https://github.com/prasadrandika) · Hire me: [prasadrandika.github.io](https://prasadrandika.github.io)
