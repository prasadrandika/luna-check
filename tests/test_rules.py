"""Small synthetic cases for each rule, language and false-positive filter."""

import json
import textwrap

import pytest

from luna_check import rules
from luna_check.cli import main
from luna_check.scanner import scan


def write(tmp_path, name, body):
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(body).lstrip("\n"), encoding="utf-8")
    return p


def hits(tmp_path, **kw):
    findings, _ = scan(tmp_path, **kw)
    return [(f.path, f.line, f.rule.id, f.severity) for f in findings]


# --- LC001 model IDs ---------------------------------------------------------

@pytest.mark.parametrize("model", [
    "gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini",
    "gpt-4o-2024-08-06", "gpt-4o-2024-11-20", "gpt-4o-mini-2024-07-18",
    "gpt-4.1-2025-04-14", "gpt-4.1-mini-2025-04-14", "openai/gpt-4o-mini",
])
def test_retiring_ids_are_found(tmp_path, model):
    write(tmp_path, "a.py", f'MODEL = "{model}"\n')
    assert hits(tmp_path) == [("a.py", 1, "LC001", "high")]


@pytest.mark.parametrize("model", [
    "gpt-4o-mini-search-preview", "gpt-4o-realtime-preview", "gpt-4o-audio-preview",
    "gpt-4.1-nano", "gpt-4o-transcribe", "gpt-4o-2024-05-13", "gpt-4", "gpt-4-turbo",
    "gpt-6-luna", "GPT-4o",
])
def test_other_models_are_not_found(tmp_path, model):
    write(tmp_path, "a.py", f'MODEL = "{model}"\n')
    assert hits(tmp_path) == []


def test_bare_alias_message_names_the_snapshots(tmp_path):
    write(tmp_path, "a.py", 'm = "gpt-4o"\n')
    (f,), _ = scan(tmp_path)
    assert "gpt-4o-2024-08-06, gpt-4o-2024-11-20" in f.message
    assert f.rule.source == rules.DEPRECATIONS_URL


def test_comments_and_docstrings_are_ignored(tmp_path):
    write(tmp_path, "a.py", '''
        """Module docstring mentions "gpt-4o-mini"."""
        # gpt-4o-mini is retired
        def f():
            """Uses gpt-4o."""
            return 1  # "gpt-4o"
    ''')
    write(tmp_path, "b.ts", '''
        // "gpt-4o-mini"
        /* model: "gpt-4.1" */
        const x = 1;
    ''')
    write(tmp_path, "c.go", '''
        package c
        // defaultModel = "gpt-4o-mini"
        /* "gpt-4.1-mini" */
        const x = 1
    ''')
    assert hits(tmp_path) == []


def test_triple_quoted_argument_is_not_a_docstring(tmp_path):
    write(tmp_path, "a.py", '''
        call(
            """gpt-4o"""
        )
    ''')
    assert hits(tmp_path) == [("a.py", 2, "LC001", "high")]


def test_js_ts_and_go_strings(tmp_path):
    write(tmp_path, "a.js", "const m = 'gpt-4o-mini';\n")
    write(tmp_path, "b.tsx", "const m = `gpt-4.1`;\n")
    write(tmp_path, "c.go", 'package c\nvar m = "gpt-4o"\nvar r = `gpt-4.1-mini`\n')
    assert hits(tmp_path) == [
        ("a.js", 1, "LC001", "high"),
        ("b.tsx", 1, "LC001", "high"),
        ("c.go", 2, "LC001", "high"),
        ("c.go", 3, "LC001", "high"),
    ]


def test_price_and_lookup_tables_are_ignored(tmp_path):
    write(tmp_path, "prices.py", '''
        PRICES = {
            "gpt-4o": {"input": 2.5, "output": 10},
            "gpt-4o-mini": 0.15,
        }
        ROWS = [{"model": "gpt-4.1", "price_per_1m": 2.0}]
    ''')
    write(tmp_path, "limits.go", '''
        package l
        var limits = map[string]int{
            "gpt-4o": 128000,
        }
    ''')
    assert hits(tmp_path) == []


def test_ternary_is_not_a_mapping_key(tmp_path):
    write(tmp_path, "a.ts", 'const m = fast ? "gpt-4o-mini" : "gpt-4o";\n')
    assert [h[2] for h in hits(tmp_path)] == ["LC001", "LC001"]


def test_prose_strings_are_ignored(tmp_path):
    write(tmp_path, "a.py", 'log.info("switching from gpt-4o-mini to the new model")\n')
    assert hits(tmp_path) == []


def test_tests_are_skipped_unless_asked(tmp_path):
    for name in ["test_a.py", "a_test.py", "a_test.go", "a.test.ts", "a.spec.js",
                 "tests/x.py", "pkg/__tests__/x.js", "testdata/x.go"]:
        write(tmp_path, name, 'm = "gpt-4o"\n' if name.endswith(".py") else 'var m = "gpt-4o";\n')
    assert hits(tmp_path) == []
    assert len(hits(tmp_path, include_tests=True)) == 8


def test_markdown_and_other_files_are_not_scanned(tmp_path):
    write(tmp_path, "README.md", '`model="gpt-4o"`\n')
    write(tmp_path, "config.yaml", "model: gpt-4o\n")
    assert hits(tmp_path) == []


def test_vendor_folders_are_skipped(tmp_path):
    write(tmp_path, "node_modules/x/index.js", 'const m = "gpt-4o";\n')
    write(tmp_path, ".venv/lib/x.py", 'm = "gpt-4o"\n')
    assert hits(tmp_path) == []


@pytest.mark.parametrize("name", ["scripts/seed-db.ts", "demo/app.py", "ui/mocks/chat.ts", "seed.go"])
def test_seed_and_demo_files_are_low(tmp_path, name):
    body = 'm = "gpt-4o"\n' if name.endswith(".py") else 'var m = "gpt-4o";\n'
    write(tmp_path, name, body)
    assert [h[3] for h in hits(tmp_path)] == ["low"]


def test_ignore_comment(tmp_path):
    write(tmp_path, "a.py", 'm = "gpt-4o"  # luna-check: ignore\nn = "gpt-4o"\n')
    assert hits(tmp_path) == [("a.py", 2, "LC001", "high")]


def test_crlf_line_numbers(tmp_path):
    (tmp_path / "a.py").write_bytes(b'x = 1\r\n# "gpt-4o"\r\nm = "gpt-4o"\r\n')
    assert hits(tmp_path) == [("a.py", 3, "LC001", "high")]


# --- LC002 tiktoken ----------------------------------------------------------

def test_tiktoken_literal(tmp_path):
    write(tmp_path, "a.py", 'enc = tiktoken.encoding_for_model("gpt-4o-mini")\n')
    assert hits(tmp_path) == [("a.py", 1, "LC002", "high")]  # no duplicate LC001


def test_tiktoken_variable(tmp_path):
    write(tmp_path, "a.py", "enc = tiktoken.encoding_for_model(MODEL)\n")
    assert hits(tmp_path) == [("a.py", 1, "LC002", "high")]


def test_tiktoken_with_fallback_is_fine(tmp_path):
    write(tmp_path, "a.py", '''
        try:
            enc = tiktoken.encoding_for_model(MODEL)
        except KeyError:
            enc = tiktoken.get_encoding("o200k_base")
    ''')
    assert hits(tmp_path) == []


def test_tiktoken_other_model_literal_is_fine(tmp_path):
    write(tmp_path, "a.py", 'enc = tiktoken.encoding_for_model("gpt-3.5-turbo")\n')
    assert hits(tmp_path) == []


def test_tiktoken_js_and_go(tmp_path):
    write(tmp_path, "a.ts", 'const enc = encodingForModel("gpt-4o");\n')
    write(tmp_path, "b.go", 'package b\nfunc f() { enc, _ := tiktoken.EncodingForModel("gpt-4.1") }\n')
    assert [h[:3] for h in hits(tmp_path)] == [("a.ts", 1, "LC002"), ("b.go", 2, "LC002")]


# --- LC004 tools on /chat/completions ---------------------------------------

def test_python_tools_without_effort(tmp_path):
    write(tmp_path, "a.py", '''
        r = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=msgs,
            tools=TOOLS,
        )
    ''')
    assert [h[1:3] for h in hits(tmp_path)] == [(1, "LC004"), (2, "LC001")]


@pytest.mark.parametrize("effort", [
    'reasoning_effort="none"',
    'extra_body={"reasoning_effort": "none"}',
])
def test_python_tools_with_effort(tmp_path, effort):
    write(tmp_path, "a.py", f'''
        r = client.chat.completions.create(
            model=MODEL, messages=msgs, tools=TOOLS, {effort},
        )
        MODEL = "gpt-6-luna"
    ''')
    assert hits(tmp_path) == []


def test_python_no_tools(tmp_path):
    write(tmp_path, "a.py", 'client.chat.completions.create(model="gpt-6-luna", messages=m)\n')
    assert hits(tmp_path) == []


def test_tools_ignored_when_file_names_no_relevant_model(tmp_path):
    write(tmp_path, "a.py", 'client.chat.completions.create(model="o3", messages=m, tools=T)\n')
    assert hits(tmp_path) == []


def test_js_tools_shorthand(tmp_path):
    write(tmp_path, "a.ts", '''
        const r = await openai.chat.completions.create({
          model: "gpt-4.1",
          messages,
          tools,
        });
    ''')
    assert [h[1:3] for h in hits(tmp_path)] == [(1, "LC004"), (2, "LC001")]


def test_responses_api_is_not_flagged(tmp_path):
    write(tmp_path, "a.py", 'client.responses.create(model="gpt-6-luna", input=x, tools=T)\n')
    assert hits(tmp_path) == []


def test_go_raw_http_without_effort(tmp_path):
    write(tmp_path, "a.go", '''
        package a
        type req struct {
            Model string `json:"model"`
            Tools []tool `json:"tools,omitempty"`
        }
        const m = "gpt-6-luna"
        func f() { http.NewRequest("POST", base+"/chat/completions", nil) }
    ''')
    assert [h[1:3] for h in hits(tmp_path)] == [(7, "LC004")]


def test_go_raw_http_with_effort(tmp_path):
    write(tmp_path, "a.go", '''
        package a
        type req struct {
            Tools []tool `json:"tools,omitempty"`
            ReasoningEffort string `json:"reasoning_effort,omitempty"`
        }
        const m = "gpt-6-luna"
        func f() { http.NewRequest("POST", base+"/chat/completions", nil) }
    ''')
    assert hits(tmp_path) == []


def test_go_sdk_call(tmp_path):
    write(tmp_path, "a.go", '''
        package a
        func f() {
            client.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
                Model: "gpt-4o",
                Tools: tools,
            })
        }
    ''')
    assert [h[1:3] for h in hits(tmp_path)] == [(3, "LC004"), (4, "LC001")]


# --- LC003 sampling parameters with reasoning on ---------------------------

def lc003(tmp_path, **kw):
    return [(h[0], h[1]) for h in hits(tmp_path, **kw) if h[2] == "LC003"]


def test_sampling_is_on_by_default(tmp_path):
    write(tmp_path, "a.py", """
        r = client.chat.completions.create(model="gpt-4o", messages=m, temperature=0.2, top_p=1)
        temperature = 5
    """)
    findings, _ = scan(tmp_path)
    got = [(f.line, f.rule.id, f.severity) for f in findings if f.rule.id == "LC003"]
    assert got == [(1, "LC003", "high"), (1, "LC003", "high")]
    assert "reasoning effort is not \"none\"" in findings[0].message or \
        "reasoning effort is not \"none\"" in findings[1].message
    assert rules.SAMPLING.source == rules.GPT6_GUIDE_URL


@pytest.mark.parametrize("param", ["temperature", "top_p", "logprobs", "top_logprobs"])
def test_each_sampling_param(tmp_path, param):
    write(tmp_path, "a.py", f'c.chat.completions.create(model="gpt-6-luna", messages=m, {param}=1)\n')
    assert lc003(tmp_path) == [("a.py", 1)]


@pytest.mark.parametrize("effort, flagged", [
    ('reasoning_effort="none"', False),
    ('extra_body={"reasoning_effort": "none"}', False),
    ('reasoning_effort="low"', True),
    ('reasoning_effort="medium"', True),
    ("reasoning_effort=EFFORT", False),  # set from a variable: cannot tell, so no finding
])
def test_sampling_and_reasoning_effort(tmp_path, effort, flagged):
    write(tmp_path, "a.py", f"""
        r = client.chat.completions.create(
            model="gpt-6-luna",
            messages=m,
            temperature=0.2,
            {effort},
        )
    """)
    assert lc003(tmp_path) == ([("a.py", 4)] if flagged else [])


def test_sampling_responses_api(tmp_path):
    write(tmp_path, "a.py", """
        a = client.responses.create(model="gpt-6-luna", input=x, top_p=0.9)
        b = client.responses.create(model="gpt-6-luna", input=x, top_p=0.9, reasoning={"effort": "none"})
        c = client.responses.create(model="gpt-6-luna", input=x, top_p=0.9, reasoning={"effort": "high"})
    """)
    assert lc003(tmp_path) == [("a.py", 1), ("a.py", 3)]


def test_sampling_langchain(tmp_path):
    write(tmp_path, "a.py", 'llm = ChatOpenAI(model="gpt-4o", temperature=0)\n')
    assert lc003(tmp_path) == [("a.py", 1)]


def test_sampling_in_params_dict(tmp_path):
    write(tmp_path, "a.py", """
        params = {"model": "gpt-4.1", "temperature": 0.3}
        safe = {"model": "gpt-4.1", "temperature": 0.3, "reasoning_effort": "none"}
    """)
    assert lc003(tmp_path) == [("a.py", 1)]


def test_sampling_null_values_are_ignored(tmp_path):
    write(tmp_path, "a.ts", 'const cfg = { model: "gpt-4o", temperature: null, top_p: undefined };\n')
    write(tmp_path, "b.py", 'c.chat.completions.create(model="gpt-4o", messages=m, temperature=None)\n')
    assert lc003(tmp_path) == []


def test_sampling_needs_a_relevant_model(tmp_path):
    write(tmp_path, "a.py", 'c.chat.completions.create(model="o3", messages=m, temperature=1)\n')
    assert lc003(tmp_path) == []


def test_sampling_js(tmp_path):
    write(tmp_path, "a.ts", """
        const a = await c.chat.completions.create({ model: "gpt-4o", messages, temperature: 0 });
        const b = await c.chat.completions.create({ model: "gpt-6-luna", messages, temperature: 0, reasoning_effort: "none" });
    """)
    assert lc003(tmp_path) == [("a.ts", 1)]


def test_sampling_go(tmp_path):
    write(tmp_path, "a.go", 'package a\nvar r = Req{Model: "gpt-4o", Temperature: 0.2}\nfunc f() { r.TopP = 0.9 }\n')
    write(tmp_path, "b.go", 'package b\nvar r = Req{Model: "gpt-6-luna", Temperature: 0.2, ReasoningEffort: "none"}\n')
    assert lc003(tmp_path) == [("a.go", 2), ("a.go", 3)]


def test_strict_flag_still_accepted(tmp_path, capsys):
    write(tmp_path, "a.py", 'm = "gpt-6-luna"\n')
    assert main([str(tmp_path), "--strict"]) == 0


# --- report and CLI ----------------------------------------------------------

def test_text_report(tmp_path, capsys):
    write(tmp_path, "a.py", 'm = "gpt-4o-mini"\n')
    assert main([str(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "a.py" in out and "line 1" in out and rules.DEPRECATIONS_URL in out
    assert out.rstrip().splitlines()[-1] == "Need help migrating? github.com/prasadrandika"


def test_clean_report_and_exit_codes(tmp_path, capsys):
    write(tmp_path, "a.py", 'm = "gpt-6-luna"\n')
    assert main([str(tmp_path)]) == 0
    assert capsys.readouterr().out.rstrip().endswith("Need help migrating? github.com/prasadrandika")
    write(tmp_path, "b.py", 'm = "gpt-4o"\n')
    assert main([str(tmp_path), "--exit-zero"]) == 0
    assert main([str(tmp_path / "missing")]) == 2


def test_low_only_does_not_fail(tmp_path):
    write(tmp_path, "seed.py", 'm = "gpt-4o"\n')
    assert main([str(tmp_path)]) == 0


def test_json_report(tmp_path, capsys):
    write(tmp_path, "a.py", 'm = "gpt-4o"\n')
    main([str(tmp_path), "--format", "json"])
    data = json.loads(capsys.readouterr().out)
    assert data["findings"][0]["rule"] == "LC001"
    assert data["findings"][0]["source"] == rules.DEPRECATIONS_URL
    assert data["footer"] == "Need help migrating? github.com/prasadrandika"


def test_every_rule_cites_an_official_source():
    for rule in rules.ALL_RULES:
        assert rule.source.startswith(("https://developers.openai.com/", "https://github.com/openai/"))
