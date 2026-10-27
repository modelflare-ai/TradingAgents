"""Small first-run connectivity check for the Modelflare gateway."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

KEYS_URL = "https://modelflare.dev/keys"
DASHBOARD_URL = "https://modelflare.dev/dashboard"
DEFAULT_BASE_URL = "https://modelflare.dev/v1"
SIGNUP_URL = "http://modelflare.dev/sign-up?utm_source=github&utm_campaign=mf_TradingAgents"

_BALANCE = re.compile(r"quota|balance|insufficient|额度|余额", re.IGNORECASE)
_MODEL_ACCESS = re.compile(r"model_not_found|分组", re.IGNORECASE)


@dataclass(frozen=True)
class SmokeResult:
    ok: bool
    message: str
    status: int | None = None


def host_is_modelflare(url: str | None) -> bool:
    """True when ``url``'s host contains modelflare.dev."""
    if not url:
        return False
    candidate = url if "://" in url else f"https://{url}"
    host = (urlparse(candidate).hostname or "").lower()
    return "modelflare.dev" in host


def missing_key_message() -> str | None:
    """Signup guidance when neither key variable is set, else None."""
    if os.environ.get("MODELFLARE_API_KEY") or os.environ.get("MODELFLARE_KEY"):
        return None
    return f"MODELFLARE_API_KEY is not set. Get a key at {SIGNUP_URL}"


def _targets_modelflare(provider, backend_url, request_url) -> bool:
    """Friendly copy only for the Modelflare host, or the Modelflare provider's own default."""
    if host_is_modelflare(backend_url) or host_is_modelflare(request_url):
        return True
    if str(provider or "").lower() != "modelflare":
        return False
    # No URL, or only empty ones: the provider's own default endpoint.
    return all(host_is_modelflare(url) for url in (backend_url, request_url) if url)


def explain_api_error(status, message, model, base_url: str | None = None) -> str | None:
    """Bilingual guidance for a known Modelflare failure, or None.

    ``base_url`` gates the copy: a host that does not contain modelflare.dev
    never gets Modelflare wording. Omit it only after the caller has already
    checked the endpoint. A plain 403 is not treated as an empty balance.
    """
    if base_url is not None and not host_is_modelflare(base_url):
        return None
    text = message or ""
    model_name = model or "the selected model"
    if status == 401:
        return (
            f"Your Modelflare API key is invalid or revoked. Get a key at {KEYS_URL}\n"
            f"Modelflare API Key 无效或已停用。请到 {KEYS_URL} 复制新的 Key。"
        )
    access = status in (403, 503) and _MODEL_ACCESS.search(text) is not None
    if status == 402 or (_BALANCE.search(text) is not None and not access):
        return (
            f"Insufficient Modelflare balance. Top up at {DASHBOARD_URL}\n"
            f"Modelflare 余额不足，请充值：{DASHBOARD_URL}"
        )
    if access:
        return (
            f"This Modelflare key's group cannot call model {model_name}. "
            f"Change the group at {KEYS_URL} or pick another model.\n"
            f"当前 Key 的分组无法调用模型 {model_name}，请在 {KEYS_URL} 调整分组，或换一个模型。"
        )
    return None


def _response_error_text(exc: HTTPError) -> str:
    """A short provider message. The API key is never read from the body."""
    try:
        payload = exc.read()
    except Exception:
        payload = b""
    if isinstance(payload, bytes):
        raw = payload.decode("utf-8", errors="replace")
    else:
        raw = str(payload or "")
    raw = raw.strip()
    if not raw:
        return str(getattr(exc, "msg", "") or "")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw[:500]
    if isinstance(parsed, dict):
        err = parsed.get("error", parsed)
        if isinstance(err, dict):
            bits = [str(err.get(key) or "") for key in ("code", "type", "message")]
            return " ".join(bit for bit in bits if bit)[:500]
        return str(err)[:500]
    return raw[:500]


def smoke_test(model: str, base_url: str | None = None, timeout: float = 15) -> SmokeResult:
    """Send one minimal Chat Completions request and return safe guidance.

    The response body is intentionally reduced to a short provider message so
    API keys and full gateway payloads never reach the terminal output.
    Friendly key, group, and balance text is used only when the endpoint host
    contains modelflare.dev.
    """
    missing = missing_key_message()
    if missing:
        return SmokeResult(False, missing)
    endpoint = (base_url or os.environ.get("MODELFLARE_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    api_key = os.environ.get("MODELFLARE_API_KEY") or os.environ.get("MODELFLARE_KEY")
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "max_tokens": 1,
        "temperature": 0,
    }).encode("utf-8")
    request = Request(
        f"{endpoint}/chat/completions",
        data=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            if 200 <= response.status < 300:
                return SmokeResult(True, f"Modelflare connected (model: {model})", response.status)
            return SmokeResult(False, f"Request to {endpoint} failed with HTTP {response.status}", response.status)
    except HTTPError as exc:
        detail = _response_error_text(exc)
        friendly = explain_api_error(exc.code, detail, model, base_url=endpoint)
        if friendly:
            return SmokeResult(False, friendly, exc.code)
        return SmokeResult(False, f"Request to {endpoint} failed with HTTP {exc.code}", exc.code)
    except (TimeoutError, URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        return SmokeResult(False, f"Could not reach Modelflare at {endpoint}: {reason}")


def unattended_smoke(provider, backend_url, model) -> SmokeResult | None:
    """One smoke call for a headless Modelflare run. None when the run is not Modelflare."""
    if not _targets_modelflare(provider, backend_url, None):
        return None
    missing = missing_key_message()
    if missing:
        return SmokeResult(False, missing)
    return smoke_test(model or "gpt-6-sol", backend_url)


def explain_run_exception(exc, provider, backend_url, model) -> str | None:
    """Map an OpenAI SDK status error from Modelflare to friendly text, else None.

    ``openai`` is imported here so unit tests that never hit a live call do not
    need the package at import time.
    """
    try:
        import openai
    except ImportError:
        return None
    if not isinstance(exc, (
        openai.APIStatusError,
        openai.AuthenticationError,
        openai.PermissionDeniedError,
        openai.RateLimitError,
    )):
        return None
    request = getattr(exc, "request", None)
    request_url = getattr(request, "url", None)
    if request_url is not None:
        request_url = str(request_url)
    if not _targets_modelflare(provider, backend_url, request_url):
        return None
    status = getattr(exc, "status_code", None)
    if status is None:
        status = getattr(getattr(exc, "response", None), "status_code", None)
    message = getattr(exc, "message", None) or str(exc)
    body = getattr(exc, "body", None)
    if body not in (None, ""):
        message = f"{message}\n{body}"
    gate_url = backend_url or request_url
    if not host_is_modelflare(gate_url):
        gate_url = DEFAULT_BASE_URL
    return explain_api_error(status, message, model or "", base_url=gate_url)
