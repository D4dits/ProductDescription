from types import SimpleNamespace

from app import llm


def test_zai_provider_uses_openai_compatible_defaults(monkeypatch):
    captured = {}

    def fake_generate_openai(prompt, system_instruction, json_mode, api_key, base_url, model, provider_label):
        captured.update(
            {
                "prompt": prompt,
                "system_instruction": system_instruction,
                "json_mode": json_mode,
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
                "provider_label": provider_label,
            }
        )
        return "{}"

    monkeypatch.setattr(llm, "_generate_openai", fake_generate_openai)

    result = llm.generate_text(
        prompt="test prompt",
        system_instruction="test system",
        json_mode=True,
        api_key="zai-test-key",
        provider="z_ai",
    )

    assert result == "{}"
    assert captured["api_key"] == "zai-test-key"
    assert captured["base_url"] == "https://api.z.ai/api/paas/v4/"
    assert captured["model"] == "glm-5.2"
    assert captured["provider_label"] == "Z.AI"


def test_zai_provider_aliases_are_supported(monkeypatch):
    called = []

    def fake_generate_openai(*args, **kwargs):
        called.append(kwargs["provider_label"])
        return "{}"

    monkeypatch.setattr(llm, "_generate_openai", fake_generate_openai)

    for provider in ["zai", "z.ai", "z-ai"]:
        assert llm.generate_text("test", api_key="zai-test-key", provider=provider) == "{}"

    assert called == ["Z.AI", "Z.AI", "Z.AI"]


def test_deepseek_provider_uses_openai_compatible_defaults(monkeypatch):
    captured = {}

    def fake_generate_openai(prompt, system_instruction, json_mode, api_key, base_url, model, provider_label):
        captured.update(
            {
                "api_key": api_key,
                "base_url": base_url,
                "model": model,
                "provider_label": provider_label,
            }
        )
        return "{}"

    monkeypatch.setattr(llm, "_generate_openai", fake_generate_openai)

    assert llm.generate_text("test prompt", api_key="deepseek-test-key", provider="deepseek") == "{}"
    assert captured["api_key"] == "deepseek-test-key"
    assert captured["base_url"] == "https://api.deepseek.com"
    assert captured["model"] == "deepseek-v4-flash"
    assert captured["provider_label"] == "DeepSeek"


def test_deepseek_provider_aliases_are_supported(monkeypatch):
    called = []

    def fake_generate_openai(*args, **kwargs):
        called.append(kwargs["provider_label"])
        return "{}"

    monkeypatch.setattr(llm, "_generate_openai", fake_generate_openai)

    for provider in ["deep_seek", "deep-seek"]:
        assert llm.generate_text("test", api_key="deepseek-test-key", provider=provider) == "{}"

    assert called == ["DeepSeek", "DeepSeek"]


def test_placeholder_keys_are_rejected(monkeypatch):
    monkeypatch.setattr(llm, "LLM_PROVIDER", "deepseek")
    monkeypatch.setattr(llm, "DEEPSEEK_API_KEY", "your_deepseek_api_key_here")

    try:
        llm.validate_llm_configuration()
    except llm.LLMError as exc:
        assert "DEEPSEEK_API_KEY" in str(exc)
    else:
        raise AssertionError("Placeholder API key should be rejected")


def test_authentication_error_has_actionable_message():
    error = RuntimeError("Authentication Fails: API key is invalid")
    error.response = SimpleNamespace(
        status_code=401,
        json=lambda: {"error": {"message": "Authentication Fails", "code": "invalid_api_key"}},
    )

    message = llm._format_provider_error("DeepSeek", error)

    assert "DeepSeek odrzucił klucz API (401)" in message
    assert ".env" in message
