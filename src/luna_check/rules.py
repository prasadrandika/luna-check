"""Rule data. Every fact here comes from the source URL stored next to it.

Model shutdown dates (LC001) live in data/models.json, generated from each
provider's official page by scripts/build_models.py.

Checked on 2026-11-19 against:
  - https://developers.openai.com/api/docs/deprecations
  - https://developers.openai.com/api/docs/models/gpt-6-luna
  - https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md ("Using GPT-6")
  - https://github.com/openai/tiktoken/blob/main/tiktoken/model.py
  - https://platform.claude.com/docs/en/about-claude/model-deprecations ("API parameter deprecations")
  - https://platform.claude.com/docs/en/api/migration-2026-10-21 ("Sampling parameters are removed")
  - https://developers.openai.com/api/docs/guides/prompting/migrate-from-prompt-object
"""

from __future__ import annotations

from dataclasses import dataclass

DEPRECATIONS_URL = "https://developers.openai.com/api/docs/deprecations"
LUNA_MODEL_URL = "https://developers.openai.com/api/docs/models/gpt-6-luna"
# "Using GPT-6" guide. Its migration quickstart names gpt-6-luna as a target model.
GPT6_GUIDE_URL = "https://developers.openai.com/api/docs/guides/latest-model/gpt-6-astra.md#migration-quickstart"
TIKTOKEN_MODEL_URL = "https://github.com/openai/tiktoken/blob/main/tiktoken/model.py"
ANTHROPIC_DEPRECATIONS_URL = "https://platform.claude.com/docs/en/about-claude/model-deprecations"

REPLACEMENT = "gpt-6-luna"
SHUTDOWN_DATE = "Jan 14, 2027"

HIGH = "high"
LOW = "low"
SEVERITY_ORDER = {HIGH: 0, LOW: 1}


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    source: str


MODEL_ID = Rule(
    "LC001",
    "Model is retired or scheduled to shut down",
    DEPRECATIONS_URL,  # each finding links the page that lists its model
)
TIKTOKEN = Rule(
    "LC002",
    "tiktoken.encoding_for_model() raises KeyError for gpt-6-luna",
    TIKTOKEN_MODEL_URL,
)
SAMPLING = Rule(
    "LC003",
    "Sampling parameter sent while reasoning effort is not \"none\"",
    GPT6_GUIDE_URL,
)
CHAT_TOOLS = Rule(
    "LC004",
    'Function tools on /chat/completions need reasoning_effort "none" on gpt-6-luna',
    LUNA_MODEL_URL,
)

CLAUDE_SAMPLING = Rule(
    "LC005",
    "Claude API rejects temperature, top_p and top_k",
    ANTHROPIC_DEPRECATIONS_URL,
)
OPENAI_ENDPOINT = Rule(
    "LC006",
    "OpenAI API feature or endpoint is retired or shutting down",
    DEPRECATIONS_URL,
)

ALL_RULES = (MODEL_ID, TIKTOKEN, SAMPLING, CHAT_TOOLS, CLAUDE_SAMPLING, OPENAI_ENDPOINT)

# Anthropic's "API parameter deprecations" table: temperature, top_p and top_k
# are removed in API version 2026-10-21 (a 400 error on every model, even at the
# default value). Older API versions return a 400 error for a non-default value
# on Claude 4.7 and later models. The SDK majors that use 2026-10-21 (Python
# anthropic 2.0.0, TypeScript @anthropic-ai/sdk 1.0.0) no longer have them.
CLAUDE_SAMPLING_PARAMS = ("temperature", "top_p", "top_k")

# OpenAI's "Feature and endpoint deprecations" and "Past deprecations" tables
# (checked 2026-11-19): (name, shutdown date, status word, replacement).
OPENAI_ENDPOINTS = {
    "assistants": ("The Assistants API", "2026-08-26", "Responses API and Conversations API"),
    "prompts": ("The reusable prompt objects feature (/v1/prompts)", "2026-11-30",
                "prompt content in your application code"),
    "evals": ("The Evals API", "2026-11-30", "Promptfoo (the Evals API becomes read-only)"),
    "audio_translations": ("/v1/audio/translations", "2027-02-26", "/v1/realtime/translations"),
    "videos": ("The Videos API", "2026-09-24", None),
    "realtime_v1": ("The OpenAI-Beta: realtime=v1 header", "2026-05-12",
                    "the GA Realtime API (see the Realtime API migration guide)"),
    "assistants_v1": ("The OpenAI-Beta: assistants=v1 header", "2024-12-18", "Responses API"),
    "legacy": ("This legacy endpoint", "2024-01-04", "the current API endpoints"),
}

# Dated snapshots in the deprecations page's "Upcoming deprecations" table,
# shutdown Jan 14, 2027, replacement gpt-6-luna, notice date Oct 14, 2026.
SNAPSHOTS = {
    "gpt-4o": ("gpt-4o-2024-08-06", "gpt-4o-2024-11-20"),
    "gpt-4o-mini": ("gpt-4o-mini-2024-07-18",),
    "gpt-4.1": ("gpt-4.1-2025-04-14",),
    "gpt-4.1-mini": ("gpt-4.1-mini-2025-04-14",),
}

DATED_IDS = {snap: alias for alias, snaps in SNAPSHOTS.items() for snap in snaps}

# tiktoken maps all four retiring models to this encoding (tiktoken/model.py).
OLD_ENCODING = "o200k_base"

# The Using GPT-6 guide (which covers gpt-6-luna) says to drop temperature, top_p
# and top_logprobs when reasoning effort is not "none", and also logprobs on Chat
# Completions. Checked 2026-11-19. The newer "Using GPT-6.2" guide at
# /guides/latest-model drops them with no effort condition, but it is written for
# gpt-6.2 models, not gpt-6-luna.
# gpt-6-luna's default reasoning effort is "medium" (gpt-6-luna model page).
SAMPLING_PARAMS = ("temperature", "top_p", "logprobs", "top_logprobs")


def model_message(model_id: str) -> str:
    """Message for LC001, worded differently for dated IDs and bare aliases."""
    if model_id in DATED_IDS:
        return (
            f'"{model_id}" shuts down on {SHUTDOWN_DATE}. '
            f'Replace it with "{REPLACEMENT}".'
        )
    snaps = ", ".join(SNAPSHOTS[model_id])
    return (
        f'"{model_id}" points to the dated snapshot(s) {snaps}, which shut down on '
        f'{SHUTDOWN_DATE}. Replace it with "{REPLACEMENT}".'
    )
