"""Rule data. Every fact here comes from the source URL stored next to it.

Checked on 2026-11-18 against:
  - https://developers.openai.com/api/docs/deprecations
  - https://developers.openai.com/api/docs/models/gpt-6-luna
  - https://developers.openai.com/api/docs/guides/latest-model/gpt-6.2-astra.md
  - https://github.com/openai/tiktoken/blob/main/tiktoken/model.py
"""

from __future__ import annotations

from dataclasses import dataclass

DEPRECATIONS_URL = "https://developers.openai.com/api/docs/deprecations"
LUNA_MODEL_URL = "https://developers.openai.com/api/docs/models/gpt-6-luna"
GPT62_GUIDE_URL = "https://developers.openai.com/api/docs/guides/latest-model/gpt-6.2-astra.md"
TIKTOKEN_MODEL_URL = "https://github.com/openai/tiktoken/blob/main/tiktoken/model.py"

REPLACEMENT = "gpt-6-luna"
SHUTDOWN_DATE = "Jan 14, 2027"

HIGH = "high"
LOW = "low"
UNCONFIRMED = "unconfirmed"

SEVERITY_ORDER = {HIGH: 0, LOW: 1, UNCONFIRMED: 2}


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    source: str


MODEL_ID = Rule(
    "LC001",
    "Model shuts down on " + SHUTDOWN_DATE,
    DEPRECATIONS_URL,
)
TIKTOKEN = Rule(
    "LC002",
    "tiktoken.encoding_for_model() raises KeyError for gpt-6-luna",
    TIKTOKEN_MODEL_URL,
)
SAMPLING = Rule(
    "LC003",
    "Sampling parameter sent (not confirmed for gpt-6-luna)",
    GPT62_GUIDE_URL,
)
CHAT_TOOLS = Rule(
    "LC004",
    'Function tools on /chat/completions need reasoning_effort "none" on gpt-6-luna',
    LUNA_MODEL_URL,
)

ALL_RULES = (MODEL_ID, TIKTOKEN, SAMPLING, CHAT_TOOLS)

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

# Parameters the GPT-6.2 guide says to omit on Chat Completions. The gpt-6-luna
# model page does not mention them, so this rule only runs with --strict.
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
