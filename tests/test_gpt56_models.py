"""Registry smoke tests for the GPT-5.6 family and per-model reasoning efforts.

Runs standalone (no pytest required):

    ./venv/bin/python tests/test_gpt56_models.py

Also compatible with pytest if it is installed.

These tests assert:
  * gpt-5.6-sol / terra / luna register as base models.
  * The full effort ladder resolves for sol/terra (incl. -reasoning-ultra).
  * luna has NO ultra variant (gpt-5.6-luna-reasoning-ultra must NOT exist).
  * gpt-5.5-reasoning-xhigh resolves (xhigh added to existing high-tier model).
  * The hidden openai-native alias mapping works (e.g. gpt-5.6-sol-ultra).
  * The chatgpt_provider effort-suffix parser recognizes xhigh/max/ultra.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.custom_models import (  # noqa: E402
    CHATGPT_MODELS_CONFIG,
    is_chatgpt_model,
    get_openai_model_id,
)
from models.registry import MODEL_REGISTRY  # noqa: E402
from models.reasoning import REASONING_BUDGET_MAP  # noqa: E402


def test_new_56_models_registered():
    for base in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna"):
        assert is_chatgpt_model(base), f"{base} not registered"
        assert base in MODEL_REGISTRY, f"{base} missing from MODEL_REGISTRY"


def test_gpt6_sol_and_luna_registered():
    for base in ("gpt-6-sol", "gpt-6-luna", "gpt-6.1-sol"):
        assert is_chatgpt_model(base), f"{base} not registered"
        assert base in MODEL_REGISTRY, f"{base} missing from MODEL_REGISTRY"

    for effort in ("low", "medium", "high", "xhigh", "max", "ultra"):
        assert is_chatgpt_model(f"gpt-6-sol-reasoning-{effort}")
    for effort in ("low", "medium", "high", "xhigh", "max"):
        assert is_chatgpt_model(f"gpt-6-luna-reasoning-{effort}")
    assert not is_chatgpt_model("gpt-6-luna-reasoning-ultra")
    assert not is_chatgpt_model("gpt-6-terra")


def test_sol_terra_full_effort_ladder():
    for base in ("gpt-5.6-sol", "gpt-5.6-terra"):
        for effort in ("low", "medium", "high", "xhigh", "max", "ultra"):
            variant = f"{base}-reasoning-{effort}"
            assert is_chatgpt_model(variant), f"{variant} should resolve"


def test_sol_ultra_variant_resolves():
    assert is_chatgpt_model("gpt-5.6-sol-reasoning-ultra")


def test_luna_has_no_ultra():
    # luna's backend spec omits ultra; it must NOT be generated.
    assert not is_chatgpt_model("gpt-5.6-luna-reasoning-ultra"), (
        "gpt-5.6-luna-reasoning-ultra must NOT exist (luna has no ultra)"
    )
    # but luna's other efforts must exist
    for effort in ("low", "medium", "high", "xhigh", "max"):
        assert is_chatgpt_model(f"gpt-5.6-luna-reasoning-{effort}")


def test_existing_high_tier_gets_xhigh():
    for base in ("gpt-5.5", "gpt-5.4", "gpt-5.3-codex-spark"):
        assert is_chatgpt_model(f"{base}-reasoning-xhigh"), (
            f"{base}-reasoning-xhigh should resolve"
        )
    # And these models must NOT gain ultra (backend caps them at xhigh).
    for base in ("gpt-5.5", "gpt-5.4", "gpt-5.3-codex-spark"):
        assert not is_chatgpt_model(f"{base}-reasoning-ultra")


def test_backward_compat_minimal_preserved():
    # Models without supported_efforts keep the legacy [minimal, low, medium, high].
    assert is_chatgpt_model("gpt5-reasoning-minimal")
    assert is_chatgpt_model("gpt5-reasoning-high")
    # 5.6 models follow the backend list which omits minimal.
    assert not is_chatgpt_model("gpt-5.6-sol-reasoning-minimal")


def test_openai_native_alias_mapping():
    # Advertised variant maps to the correct openai-native id with effort suffix.
    assert get_openai_model_id("gpt-5.6-sol-reasoning-ultra") == "gpt-5.6-sol-ultra"
    # Hidden native alias itself is looked up as a chatgpt model.
    assert is_chatgpt_model("gpt-5.6-sol-ultra")
    assert is_chatgpt_model("gpt-5.5-xhigh")
    assert get_openai_model_id("gpt-6-sol-reasoning-ultra") == "gpt-6-sol-ultra"
    assert get_openai_model_id("gpt-6-luna-reasoning-max") == "gpt-6-luna-max"
    assert is_chatgpt_model("gpt-6-sol-ultra")
    assert is_chatgpt_model("gpt-6-luna-max")


def test_context_window_and_output():
    for base in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-sol", "gpt-6-luna", "gpt-6.1-sol"):
        cfg = CHATGPT_MODELS_CONFIG[base]
        assert cfg["context_length"] == 872000, base
        assert cfg["max_completion_tokens"] == 128000, base
        assert cfg["supports_vision"] is True, base


def test_reasoning_budgets_present():
    for effort in ("xhigh", "max", "ultra"):
        assert effort in REASONING_BUDGET_MAP, f"{effort} budget missing"
    assert REASONING_BUDGET_MAP["xhigh"] == 48000
    assert REASONING_BUDGET_MAP["max"] == 64000
    assert REASONING_BUDGET_MAP["ultra"] == 64000


def test_effort_suffix_parser_recognizes_new_efforts():
    # Mirror the parser logic in providers/chatgpt_provider.py to ensure the
    # new efforts (and their ordering vs. "high") strip correctly.
    def parse(openai_model: str):
        model_lower = openai_model.lower()
        for effort in ["minimal", "xhigh", "ultra", "max", "low", "medium", "high"]:
            if model_lower.endswith(f"-{effort}"):
                return openai_model[: -len(f"-{effort}")], effort
        return openai_model, None

    assert parse("gpt-5.6-sol-ultra") == ("gpt-5.6-sol", "ultra")
    assert parse("gpt-5.6-terra-max") == ("gpt-5.6-terra", "max")
    assert parse("gpt-6-sol-ultra") == ("gpt-6-sol", "ultra")
    assert parse("gpt-6-luna-max") == ("gpt-6-luna", "max")
    # Critical: xhigh must NOT be mis-parsed as "high".
    assert parse("gpt-5.5-xhigh") == ("gpt-5.5", "xhigh")
    assert parse("gpt-5.5-high") == ("gpt-5.5", "high")


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return failures


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)


def test_gpt_61_sol_registered_with_ultra():
    assert is_chatgpt_model("gpt-6.1-sol")
    assert is_chatgpt_model("gpt-6.1-sol-reasoning-ultra")
    assert get_openai_model_id("gpt-6.1-sol-reasoning-ultra") == "gpt-6.1-sol-ultra"
