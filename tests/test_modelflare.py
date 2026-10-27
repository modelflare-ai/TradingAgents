"""Modelflare smoke check and friendly API errors. No network."""

from __future__ import annotations

import email.message
import sys
import types
from io import BytesIO
from urllib.error import HTTPError

import pytest

from tradingagents.llm_clients import modelflare
from tradingagents.llm_clients.modelflare import (
    SIGNUP_URL,
    SmokeResult,
    explain_api_error,
    explain_run_exception,
    smoke_test,
    unattended_smoke,
)
from tradingagents.llm_clients.validators import validate_model

MODEL = "gpt-6-sol"
MF_URL = "https://modelflare.dev/v1"
OTHER_URL = "https://api.openai.com/v1"


def _http_error(code: int, body: str) -> HTTPError:
    return HTTPError(
        url=f"{MF_URL}/chat/completions",
        code=code,
        msg="error",
        hdrs=email.message.EmailMessage(),
        fp=BytesIO(body.encode()),
    )


def _raise_http(code: int, body: str):
    def _open(*args, **kwargs):
        raise _http_error(code, body)

    return _open


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("MODELFLARE_API_KEY", "sk-test")
    monkeypatch.delenv("MODELFLARE_KEY", raising=False)


def test_custom_modelflare_model_does_not_warn():
    assert validate_model("modelflare", "my-gateway-model") is True


def test_401_names_the_key():
    text = explain_api_error(401, "invalid", MODEL)
    assert text is not None
    assert "Your Modelflare API key is invalid or revoked." in text
    assert "https://modelflare.dev/keys" in text
    assert "Modelflare API Key 无效或已停用。请到 https://modelflare.dev/keys 复制新的 Key。" in text


def test_402_names_the_balance():
    text = explain_api_error(402, "payment required", MODEL)
    assert text is not None
    assert "Insufficient Modelflare balance. Top up at https://modelflare.dev/wallet" in text
    assert "Modelflare 余额不足，请充值：https://modelflare.dev/wallet" in text


def test_403_model_not_found_names_the_group_not_the_balance():
    text = explain_api_error(403, "model_not_found", "claude-opus-5-5")
    assert text is not None
    assert "cannot call model claude-opus-5-5" in text
    assert "https://modelflare.dev/keys" in text
    assert "当前 Key 的分组无法调用模型 claude-opus-5-5" in text
    assert "余额" not in text


def test_plain_403_is_not_a_balance_error():
    assert explain_api_error(403, "forbidden", MODEL) is None


def test_403_balance_words_are_balance_not_a_group_block():
    text = explain_api_error(403, "insufficient quota", MODEL)
    assert text is not None
    assert "Insufficient Modelflare balance" in text
    assert "cannot call model" not in text


def test_503_model_not_found_names_the_group():
    text = explain_api_error(503, "model_not_found: no route", MODEL)
    assert text is not None
    assert f"cannot call model {MODEL}" in text
    assert "分组无法调用模型" in text


def test_non_modelflare_host_returns_none():
    assert explain_api_error(401, "invalid", MODEL, base_url=OTHER_URL) is None
    assert explain_api_error(402, "quota", MODEL, base_url=OTHER_URL) is None
    assert explain_api_error(403, "model_not_found", MODEL, base_url="https://example.com/v1") is None
    assert unattended_smoke("openai", OTHER_URL, MODEL) is None


def test_smoke_401_402_403_and_503_use_the_friendly_text(monkeypatch, api_key):
    cases = [
        (401, '{"error":{"message":"invalid api key"}}', "invalid or revoked"),
        (402, '{"error":{"message":"payment required"}}', "Insufficient Modelflare balance"),
        (403, '{"error":{"code":"model_not_found","message":"no access"}}', "cannot call model"),
        (503, '{"error":{"message":"model_not_found"}}', "分组无法调用模型"),
    ]
    for code, body, snippet in cases:
        monkeypatch.setattr(modelflare, "urlopen", _raise_http(code, body))
        result = smoke_test(MODEL, MF_URL)
        assert result.ok is False and result.status == code
        assert snippet in result.message
        assert "sk-test" not in result.message


def test_smoke_plain_403_does_not_claim_a_balance_problem(monkeypatch, api_key):
    monkeypatch.setattr(modelflare, "urlopen", _raise_http(403, '{"error":{"message":"forbidden"}}'))
    result = smoke_test(MODEL, MF_URL)
    assert "Insufficient Modelflare balance" not in result.message
    assert "cannot call model" not in result.message
    assert "HTTP 403" in result.message


def test_smoke_non_modelflare_url_stays_generic(monkeypatch, api_key):
    monkeypatch.setattr(modelflare, "urlopen", _raise_http(401, "invalid"))
    result = smoke_test(MODEL, OTHER_URL)
    assert result.ok is False
    assert "invalid or revoked" not in result.message
    assert "HTTP 401" in result.message


def test_smoke_success_does_not_read_the_body(monkeypatch, api_key):
    seen = {}

    class _Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _open(request, timeout):
        seen["url"] = request.full_url
        seen["auth"] = request.get_header("Authorization")
        seen["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(modelflare, "urlopen", _open)
    result = smoke_test(MODEL, MF_URL, timeout=3)
    assert result == SmokeResult(True, f"Modelflare connected (model: {MODEL})", 200)
    assert seen["url"] == f"{MF_URL}/chat/completions"
    assert seen["auth"] == "Bearer sk-test"
    assert seen["timeout"] == 3


def test_missing_key_names_signup_and_does_not_call_out(monkeypatch):
    monkeypatch.delenv("MODELFLARE_API_KEY", raising=False)
    monkeypatch.delenv("MODELFLARE_KEY", raising=False)

    def _open(*args, **kwargs):
        raise AssertionError("network")

    monkeypatch.setattr(modelflare, "urlopen", _open)
    result = smoke_test(MODEL, MF_URL)
    assert result.ok is False
    assert SIGNUP_URL in result.message
    assert unattended_smoke("modelflare", None, MODEL).message == result.message


def test_legacy_key_is_accepted_without_prompting_the_network_name(monkeypatch):
    monkeypatch.delenv("MODELFLARE_API_KEY", raising=False)
    monkeypatch.setenv("MODELFLARE_KEY", "sk-legacy")
    monkeypatch.setattr(modelflare, "urlopen", _raise_http(401, "nope"))
    result = smoke_test(MODEL, MF_URL)
    assert "invalid or revoked" in result.message
    assert "sk-legacy" not in result.message


def _fake_openai(monkeypatch):
    openai = types.ModuleType("openai")

    class APIStatusError(Exception):
        def __init__(self, message, status_code, body=None):
            super().__init__(message)
            self.message = message
            self.status_code = status_code
            self.body = body

    openai.APIStatusError = APIStatusError
    openai.AuthenticationError = type("AuthenticationError", (APIStatusError,), {})
    openai.PermissionDeniedError = type("PermissionDeniedError", (APIStatusError,), {})
    openai.RateLimitError = type("RateLimitError", (APIStatusError,), {})
    monkeypatch.setitem(sys.modules, "openai", openai)
    return openai


def test_run_exception_non_modelflare_returns_none(monkeypatch):
    openai = _fake_openai(monkeypatch)
    exc = openai.APIStatusError("invalid", 401)
    assert explain_run_exception(exc, "openai", OTHER_URL, MODEL) is None


def test_run_exception_modelflare_401_is_friendly(monkeypatch):
    openai = _fake_openai(monkeypatch)
    exc = openai.AuthenticationError("invalid", 401)
    text = explain_run_exception(exc, "modelflare", None, MODEL)
    assert text is not None and "invalid or revoked" in text


def test_run_exception_uses_a_modelflare_request_host(monkeypatch):
    openai = _fake_openai(monkeypatch)
    exc = openai.PermissionDeniedError("model_not_found", 403, body={"error": "model_not_found"})
    exc.request = types.SimpleNamespace(url=f"{MF_URL}/chat/completions")
    text = explain_run_exception(exc, "openai", OTHER_URL, "grok-4.7")
    assert text is not None and "cannot call model grok-4.7" in text


def test_run_exception_ignores_a_modelflare_provider_pointed_elsewhere(monkeypatch):
    openai = _fake_openai(monkeypatch)
    exc = openai.RateLimitError("slow down", 429)
    assert explain_run_exception(exc, "modelflare", "https://example.internal/v1", MODEL) is None


def test_unattended_ticker_without_a_key_prints_signup_and_does_not_prompt(monkeypatch, capsys):
    import typer

    import cli.prompts as prompts
    import cli.run as run

    monkeypatch.setattr(run.sys.stdin, "isatty", lambda: False)
    monkeypatch.delenv("MODELFLARE_API_KEY", raising=False)
    monkeypatch.delenv("MODELFLARE_KEY", raising=False)
    monkeypatch.delenv("TRADINGAGENTS_LLM_PROVIDER", raising=False)
    monkeypatch.setattr(
        prompts.questionary, "password", lambda *a, **k: (_ for _ in ()).throw(AssertionError("prompted")),
    )
    monkeypatch.setattr(run, "get_user_selections", lambda flags=None: (_ for _ in ()).throw(AssertionError("prompts")))

    with pytest.raises(typer.Exit) as caught:
        run.run_analysis(flags={"ticker": "NVDA"})

    assert caught.value.exit_code == 1
    assert SIGNUP_URL in capsys.readouterr().out


def test_unattended_modelflare_run_smokes_once_before_the_graph(monkeypatch):
    import typer

    import cli.run as run

    monkeypatch.setattr(run.sys.stdin, "isatty", lambda: False)
    for name, value in {
        "TRADINGAGENTS_OUTPUT_LANGUAGE": "English",
        "TRADINGAGENTS_MAX_DEBATE_ROUNDS": "1",
        "TRADINGAGENTS_MAX_RISK_ROUNDS": "1",
        "TRADINGAGENTS_LLM_PROVIDER": "modelflare",
        "TRADINGAGENTS_QUICK_THINK_LLM": "gpt-6-sol",
        "TRADINGAGENTS_DEEP_THINK_LLM": "gpt-6-sol",
        "MODELFLARE_API_KEY": "sk-test",
    }.items():
        monkeypatch.setenv(name, value)
    calls = []

    def _smoke(provider, backend_url, model):
        calls.append((provider, backend_url, model))
        return SmokeResult(False, "stopped before the graph")

    monkeypatch.setattr(modelflare, "unattended_smoke", _smoke)
    monkeypatch.setattr(run, "TradingAgentsGraph", lambda *a, **k: (_ for _ in ()).throw(AssertionError("graph")))

    flags = {"ticker": "NVDA", "date": "2026-09-23", "analysts": "market,news", "save": True, "show": False}
    with pytest.raises(typer.Exit):
        run.run_analysis(flags=flags)

    assert calls == [("modelflare", "https://modelflare.dev/v1", MODEL)]
