"""0.3.0: model catalogs are LOW, and config files are scanned."""

import textwrap

import pytest

from luna_check.config import is_model_key
from luna_check.scanner import scan


def write(tmp_path, name, body):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return p


def hits(tmp_path, **kw):
    findings, _ = scan(tmp_path, **kw)
    return [(f.path, f.line, f.rule.id, f.severity) for f in findings]


# --- model catalogs in code ----------------------------------------------------

def test_go_catalog_is_low(tmp_path):
    write(tmp_path, "models.go", '''
        package m

        var known = []string{
            "gpt-3.5-turbo",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-5",
            "o3",
        }

        const defaultModel = "gpt-4o-mini"
    ''')
    assert hits(tmp_path) == [
        ("models.go", 5, "LC001", "low"),
        ("models.go", 6, "LC001", "low"),
        ("models.go", 11, "LC001", "high"),  # a single default stays HIGH
    ]


def test_python_and_js_catalogs_are_low(tmp_path):
    write(tmp_path, "allowed.py", '''
        ALLOWED_MODELS = {"gpt-4o", "gpt-4.1", "gpt-5", "claude-sonnet-4-5"}
        SUPPORTED = ("gpt-4o-mini", "gpt-4.1-mini", "o3-mini", "gemini-2.5-pro")
    ''')
    write(tmp_path, "models.ts", '''
        export const MODELS = ["gpt-4o", "gpt-4o-mini", "gpt-5", "gpt-6-luna"];
    ''')
    assert {h[3] for h in hits(tmp_path)} == {"low"}
    assert len(hits(tmp_path)) == 6


def test_catalog_entries_say_why_they_are_low(tmp_path):
    write(tmp_path, "m.ts", 'const MODELS = ["gpt-4o", "gpt-4.1", "gpt-5", "o3"];\n')
    findings, _ = scan(tmp_path)
    assert [f.low_reason for f in findings] == ["model list", "model list"]
    assert "list of many model names" in findings[0].message


@pytest.mark.parametrize("body", [
    'client.chat.completions.create(model="gpt-4o", messages=msgs)\n',
    'resp = client.responses.create(model="gpt-4o-mini", input="hi", temperature=None)\n',
    'MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")\n',
    'FALLBACKS = ["gpt-4o", "gpt-4o-mini"]\n',  # two models: a real fallback chain
    'FALLBACKS = ["gpt-4o", "gpt-4o-mini", "gpt-4o"]\n',  # three entries, two distinct names
])
def test_single_model_use_stays_high(tmp_path, body):
    write(tmp_path, "app.py", body)
    assert {h[3] for h in hits(tmp_path)} == {"high"}


def test_nested_lists_are_counted_separately(tmp_path):
    # The outer list holds four models, but only through inner lists of two.
    write(tmp_path, "tiers.py", '''
        TIERS = [
            ["gpt-4o", "gpt-4o-mini"],
            ["gpt-5", "o3"],
        ]
    ''')
    assert {h[3] for h in hits(tmp_path)} == {"high"}


def test_prose_strings_do_not_make_a_catalog(tmp_path):
    write(tmp_path, "a.py", '''
        call("gpt-4o", "hello there", "another sentence", "more text", "x y")
    ''')
    assert hits(tmp_path) == [("a.py", 1, "LC001", "high")]


# --- config files ----------------------------------------------------------------

@pytest.mark.parametrize("key", [
    "model", "MODEL", "model_name", "modelName", "model_id", "default_model",
    "defaultModel", "OPENAI_MODEL", "llm_model", "LLM_MODEL", "chat-model",
    "fallback_models", "AZURE_OPENAI_MODEL_NAME", "summary.model",
])
def test_model_like_keys(key):
    assert is_model_key(key)


@pytest.mark.parametrize("key", [
    "title", "description", "modelling", "model_path", "temperature",
    "OPENAI_API_KEY", "provider", "remodel", "embedding_dim",
])
def test_other_keys(key):
    assert not is_model_key(key)


def test_env_file(tmp_path):
    write(tmp_path, ".env", '''
        OPENAI_API_KEY=sk-test
        OPENAI_MODEL=gpt-4o-mini
        # OPENAI_MODEL=gpt-4o
        export LLM_MODEL="gpt-4.1"
        GREETING=gpt-4o
    ''')
    assert hits(tmp_path) == [(".env", 2, "LC001", "high"), (".env", 4, "LC001", "high")]


@pytest.mark.parametrize("name", [".env.example", ".env.sample", ".env.template",
                                  "config.example.yaml", "config/sample.json",
                                  "examples/app/config.toml", "settings.dist.json"])
def test_example_configs_are_low(tmp_path, name):
    if name.startswith(".env"):
        body = "OPENAI_MODEL=gpt-4o\n"
    elif name.endswith(".yaml"):
        body = "model: gpt-4o\n"
    elif name.endswith(".json"):
        body = '{"model": "gpt-4o"}\n'
    else:
        body = 'model = "gpt-4o"\n'
    write(tmp_path, name, body)
    findings, _ = scan(tmp_path)
    assert [(f.severity, f.low_reason) for f in findings] == [("low", "example config")]


def test_yaml(tmp_path):
    write(tmp_path, "config.yaml", '''
        llm:
          provider: openai
          model: gpt-4o  # main model
          defaultModel: "gpt-4.1-mini"
          description: gpt-4o
          fallback_models: [gpt-4o-mini]
        services:
          api:
            environment:
              - OPENAI_MODEL=gpt-4o-mini
              - FOO=gpt-4o
        env:
          - name: OPENAI_MODEL
            value: gpt-4.1
          - name: OTHER
            value: gpt-4o
    ''')
    assert hits(tmp_path) == [
        ("config.yaml", 3, "LC001", "high"),
        ("config.yaml", 4, "LC001", "high"),
        ("config.yaml", 6, "LC001", "high"),
        ("config.yaml", 10, "LC001", "high"),
        ("config.yaml", 14, "LC001", "high"),
    ]


def test_yaml_model_list_is_low(tmp_path):
    write(tmp_path, "models.yml", '''
        allowed_models:
          - gpt-4o
          - gpt-4.1
          - gpt-5
          - o3
        default_model: gpt-4o-mini
    ''')
    assert hits(tmp_path) == [
        ("models.yml", 2, "LC001", "low"),
        ("models.yml", 3, "LC001", "low"),
        ("models.yml", 6, "LC001", "high"),
    ]


def test_json(tmp_path):
    write(tmp_path, "settings.json", '''
        {
          "model": "gpt-4o-2024-08-06",
          "title": "gpt-4o",
          "agent": {"llm_model": "gpt-4.1"},
          "models": ["gpt-4o", "gpt-4.1", "gpt-5", "claude-sonnet-4-5"],
          "model_name": "gpt-6-luna"
        }
    ''')
    assert hits(tmp_path) == [
        ("settings.json", 2, "LC001", "high"),
        ("settings.json", 4, "LC001", "high"),
        ("settings.json", 5, "LC001", "low"),  # gpt-4o
        ("settings.json", 5, "LC001", "low"),  # gpt-4.1
    ]


def test_json_price_and_usage_records_are_ignored(tmp_path):
    write(tmp_path, "prices.json", '''
        [
          {"model": "gpt-4.1", "input_price_per_1m": 2, "currency": "USD"},
          {"model": "gpt-4o-mini", "input_tokens": 12, "cost_usd": 0.0001}
        ]
    ''')
    assert hits(tmp_path) == []


def test_toml(tmp_path):
    write(tmp_path, "app.toml", '''
        [llm]
        model = "gpt-4o"  # main
        model_id = "gpt-4o-2024-05-13"
        supported_models = [
          "gpt-4o",
          "gpt-4.1",
          "gpt-5",
          "o3",
        ]
    ''')
    assert hits(tmp_path) == [
        ("app.toml", 2, "LC001", "high"),
        ("app.toml", 5, "LC001", "low"),
        ("app.toml", 6, "LC001", "low"),
    ]


@pytest.mark.parametrize("name", [
    "package.json", "package-lock.json", "pnpm-lock.yaml", "composer.json",
    "pyproject.toml", "Cargo.toml", "yarn-lock.yaml", "deps.lock.json",
])
def test_lockfiles_and_package_files_are_ignored(tmp_path, name):
    body = 'model = "gpt-4o"\n' if name.endswith(".toml") else (
        "model: gpt-4o\n" if name.endswith(".yaml") else '{"model": "gpt-4o"}\n')
    write(tmp_path, name, body)
    assert hits(tmp_path) == []


@pytest.mark.parametrize("folder", ["testing", "__live__", "__snapshots__", "cassettes",
                                    "tests", "node_modules"])
def test_recorded_data_folders_are_ignored(tmp_path, folder):
    write(tmp_path, f"ui/{folder}/resp.json", '{"model": "gpt-4o-mini"}\n')
    assert hits(tmp_path) == []


def test_config_ignore_comment_and_crlf(tmp_path):
    (tmp_path / "c.yaml").write_bytes(b"a: 1\r\nmodel: gpt-4o  # luna-check: ignore\r\nmodel_name: gpt-4o\r\n")
    assert hits(tmp_path) == [("c.yaml", 3, "LC001", "high")]


def test_seed_config_is_low(tmp_path):
    write(tmp_path, "seed/agents.json", '{"model": "gpt-4o"}\n')
    findings, _ = scan(tmp_path)
    assert [(f.severity, f.low_reason) for f in findings] == [("low", "seed/demo file")]


def test_config_findings_name_the_key(tmp_path):
    write(tmp_path, ".env", "OPENAI_MODEL=gpt-4o-mini\n")
    (f,), _ = scan(tmp_path)
    assert 'Config key "OPENAI_MODEL"' in f.message
    assert f.fix == 'Set OPENAI_MODEL to "gpt-6-luna".'
