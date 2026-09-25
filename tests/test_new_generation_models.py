"""Smoke tests for the newly exposed Opus 5.5 model."""

from models.registry import MODEL_REGISTRY, OPENAI_MODELS_LIST


def test_opus_55_and_native_alias_are_registered():
    listed = {model["id"] for model in OPENAI_MODELS_LIST}
    assert "opus-5-5" in listed
    assert "claude-opus-5-5" in MODEL_REGISTRY
    assert MODEL_REGISTRY["opus-5-5"].anthropic_id == "claude-opus-5-5"


def test_opus_55_reasoning_variants_are_registered():
    for level in ("low", "medium", "high"):
        assert f"opus-5-5-reasoning-{level}" in MODEL_REGISTRY
        assert f"claude-opus-5-5-reasoning-{level}" in MODEL_REGISTRY
