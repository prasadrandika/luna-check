# luna-check

Find the code that will break when OpenAI shuts down **GPT-4o, GPT-4o mini, GPT-4.1 and GPT-4.1 mini** in the API on **Jan 14, 2027**.

Other tools only search for model names. luna-check also finds the problems that show up in real migrations to `gpt-6-luna`, OpenAI's recommended replacement:

| Rule | What it finds | Source |
|---|---|---|
| **LC001** | A retiring model ID: `gpt-4o`, `gpt-4o-mini`, `gpt-4.1`, `gpt-4.1-mini` and their dated snapshots. Bare names like `gpt-4o-mini` point to the dated snapshots listed on the deprecations page. | [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations) |
| **LC002** | A `tiktoken.encoding_for_model()` call. tiktoken has no entry for `gpt-6-luna`, so after the switch the call raises `KeyError`. This was checked with tiktoken 0.7.0 and 0.14.0. | [tiktoken/model.py](https://github.com/openai/tiktoken/blob/main/tiktoken/model.py) |
| **LC004** | Function tools sent to `/chat/completions` without `reasoning_effort`. On Chat Completions, gpt-6-luna supports function calling only with `reasoning_effort` set to `none`. | [gpt-6-luna model page](https://developers.openai.com/api/docs/models/gpt-6-luna) |
| **LC003** *(only with `--strict`)* | Calls that set `temperature`, `top_p`, `logprobs` or `top_logprobs`. **Not confirmed for gpt-6-luna.** OpenAI's GPT-6.2 guide says to omit these, but the gpt-6-luna page doesn't mention them. | [GPT-6.2 migration guide](https://developers.openai.com/api/docs/guides/latest-model/gpt-6.2-astra.md) |

Each finding in the report includes its source link.

## Install

```bash
pip install git+https://github.com/prasadrandika/luna-check@v0.1.0
```

It needs Python 3.9 or newer and Git, has no dependencies, and works on Windows, macOS and Linux. It is not on PyPI yet.

## Use

```bash
luna-check path/to/project
```

```
luna-check 0.1.0: scanned 3 file(s) in path/to/project

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
| `--strict` | Also report LC003 (sampling settings; not confirmed for gpt-6-luna). |
| `--include-tests` | Also scan test files. They are skipped by default. |
| `--format json` | Machine-readable output. |
| `--exit-zero` | Always exit 0. |

**Exit codes:** `1` if any HIGH finding was found, `0` if not, and `2` if the path doesn't exist. LOW and UNCONFIRMED findings never fail the run.

## GitHub Action

```yaml
- uses: actions/checkout@v4
- uses: prasadrandika/luna-check@v0.1.0
  with:
    path: .          # folder to scan
    strict: false    # true = also report LC003
    fail: true       # false = report only, never fail the job
```

## How it avoids false positives

- It scans `.py`, `.js`, `.jsx`, `.ts`, `.tsx`, `.mjs`, `.cjs` and `.go` files. It does not scan Markdown, YAML or `.env` files.
- **Comments and Python docstrings are ignored.** A small lexer removes them before any check runs.
- **Tests are skipped:** `tests/`, `test/`, `__tests__/`, `testdata/`, `test_*.py`, `*_test.py`, `*_test.go`, `*.test.ts`, `*.spec.js` and similar.
- **Price and lookup tables are skipped.** That covers a model name used as a mapping key (`{"gpt-4o": 2.5}`) and any line that mentions price, cost or per-1M.
- **Prose is skipped.** A string that contains spaces, such as a log message or a prompt, is not treated as a model setting.
- **Seed, demo, mock, fixture and sample files** are reported as LOW.
- Folders like `node_modules`, `vendor`, `.venv`, `dist` and `build` are skipped.
- To silence one line, add a comment containing `luna-check: ignore` on that line.

## Limits

luna-check reads code. It does not run it. It won't see a model name that comes only from an environment variable or a config file, and it can't follow a request built in a different file from where it is sent. A clean report means none of these known patterns were found. It does not prove the migration will work, so test your app against `gpt-6-luna` too.

## Tested on real migrations

Five real projects were migrated off `gpt-4o-mini`: Basic-Rag, youtube_transcription_api, dsl, Nasiko and WeClaw. The tests check two things: luna-check finds every problem each migration fixed in the "before" version, and it reports nothing in the "after" version. Files from the three projects with an open-source license are stored in `tests/fixtures/real/` with their licenses. The other two projects have no license, so their files are downloaded at pinned commits when the tests run.

## License

MIT

---

Need help migrating? [github.com/prasadrandika](https://github.com/prasadrandika)
