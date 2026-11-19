# luna-check

Find the code that will break when OpenAI shuts down **GPT-4o, GPT-4o mini, GPT-4.1 and GPT-4.1 mini** in the API on **Jan 14, 2027**.

Other tools only search for model names. luna-check also finds the problems that show up in real migrations to `gpt-6-luna`, OpenAI's recommended replacement:

| Rule | What it finds | Source |
|---|---|---|
| **LC001** | A retiring model ID: `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, `gpt-4.1-mini` and their dated snapshots, in code or as the value of a model setting in a config file. Bare names like `gpt-4o-mini` point to the dated snapshots listed on the deprecations page. | [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations) |
| **LC002** | A `tiktoken.encoding_for_model()` call. tiktoken has no entry for `gpt-6-luna`, so after the switch the call raises `KeyError`. This was checked with tiktoken 0.7.0 and 0.14.0. | [tiktoken/model.py](https://github.com/openai/tiktoken/blob/main/tiktoken/model.py) |
| **LC003** | A request that sets `temperature`, `top_p`, `top_logprobs` or `logprobs` without setting reasoning effort to `"none"`. OpenAI's guide says to remove these when reasoning effort is not `none`, and gpt-6-luna defaults to `medium`. | [Using GPT-6: migration quickstart](https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart), [gpt-6-luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| **LC004** | Function tools sent to `/chat/completions` without `reasoning_effort`. On Chat Completions, gpt-6-luna supports function calling only with `reasoning_effort` set to `none`. | [gpt-6-luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) |

Each finding in the report includes its source link.

## Install

```bash
pip install git+https://github.com/prasadrandika/luna-check@v0.3.0
```

It needs Python 3.9 or newer and Git, has no dependencies, and works on Windows, macOS and Linux. It is not on PyPI yet.

## Use

```bash
luna-check path/to/project
```

```
luna-check 0.3.0: scanned 3 file(s) in path/to/project

app.py
  line 43  HIGH  LC002  tiktoken.encoding_for_model() raises KeyError for gpt-6-luna
      Called with "gpt-4o-mini". tiktoken has no entry for "gpt-6-luna", so after the switch this raises KeyError (checked with tiktoken 0.7.0 and 0.14.0).
      Fix: Catch the error and fall back to get_encoding("o200k_base"), the encoding tiktoken uses for gpt-4o, gpt-4o-mini, gpt-4.1 and gpt-4.1-mini.
      Source: https://github.com/openai/tiktoken/blob/main/tiktoken/model.py
  line 73  HIGH  LC001  Model shuts down on Jan 14, 2027
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
- uses: prasadrandika/luna-check@v0.3.0
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

LC003 reports a sampling setting only when reasoning effort is missing or set to something other than `"none"`. If reasoning effort comes from a variable, luna-check can't tell its value, so it reports nothing.

## Changes

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

luna-check reads code. It does not run it. It won't see a model name that is set only at deploy time, such as a secret or a CI variable, and it can't follow a request built in a different file from where it is sent. A clean report means none of these known patterns were found. It does not prove the migration will work, so test your app against `gpt-6-luna` too.

## Tested on real migrations

Five real projects were migrated off `gpt-4o-mini`: Basic-Rag, youtube_transcription_api, dsl, Nasiko and WeClaw. The tests check two things: luna-check finds every problem each migration fixed in the "before" version, and it reports nothing in the "after" version. Files from the three projects with an open-source license are stored in `tests/fixtures/real/` with their licenses. One unchanged file from [grafana/ai-sdk](https://github.com/grafana/ai-sdk) (Apache-2.0), its list of known OpenAI model IDs, tests that model catalogs are reported as LOW. The other two projects have no license, so their files are downloaded at pinned commits when the tests run.

## Further reading

- [Migrating from GPT-4.x to GPT-6 Luna](https://help.openai.com/en/articles/20001600-migrating-from-gpt-4x-to-gpt-6-luna) (OpenAI Help Center)

## License

MIT

---

Need help migrating? [github.com/prasadrandika](https://github.com/prasadrandika) · Hire me: [prasadrandika.github.io](https://prasadrandika.github.io)
