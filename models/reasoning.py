"""Reasoning effort to thinking budget mapping"""

from typing import Dict

# Reasoning effort to thinking budget mapping (tokens)
# Budgets scale with effort. xhigh/max/ultra are the higher-effort levels
# exposed by the GPT-5.x/5.6 families (backend efforts: low, medium, high,
# xhigh, max, ultra). Values chosen to grow monotonically above "high"
# while staying within the models' 128k max_completion_tokens cap:
#   xhigh -> 48000, max -> 64000, ultra -> 64000 (ultra == max ceiling).
REASONING_BUDGET_MAP: Dict[str, int] = {
    "low": 8000,
    "medium": 16000,
    "high": 32000,
    "xhigh": 48000,
    "max": 64000,
    "ultra": 64000,
    "ultrathink": 32000,  # Max budget for ultrathink keyword
}
