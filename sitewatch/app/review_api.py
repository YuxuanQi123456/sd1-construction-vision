"""Small Responses API adapter for an explicitly requested head-region opinion.

Credentials belong to this checkout's ignored local JSON. Status checks never
contact a service, and a paid request is never retried or redirected here.
"""
from __future__ import annotations

import base64
from http.client import HTTPException
import ipaddress
import json
import math
from pathlib import Path
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

LOCAL_CONFIG = "config/review-api.local.json"
DEFAULT_CONFIG = {
    "provider": "openai",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-6.1-sol",
    "reasoning_effort": "max",
    "api_key": "",
    "timeout_seconds": 180,
    "max_output_tokens": 4096,
    "summary_max_output_tokens": 8192,
}
MAX_CONFIG_BYTES = 64 * 1024
MAX_CROP_BYTES = 20 * 1024 * 1024
MAX_SUMMARY_IMAGE_BYTES = 20 * 1024 * 1024
MAX_SUMMARY_TOTAL_BYTES = 40 * 1024 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
EFFORTS = {"low", "medium", "high", "xhigh", "max"}


class ReviewAPIError(ValueError):
    """An intentionally safe error suitable for the page and saved attempt."""


def _redact(value, secret=""):
    text = str(value)
    if secret:
        text = text.replace(secret, "[REDACTED]")
    text = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", text)
    return re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED]", text)


def _loopback(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _base_url(value):
    if not isinstance(value, str) or not value.strip() or any(c.isspace() for c in value):
        raise ReviewAPIError("复核配置中的 base_url 无效")
    value = value.rstrip("/")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ReviewAPIError("复核配置中的 base_url 无效") from None
    if (not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or "\\" in value
            or parsed.scheme not in {"http", "https"}
            or (parsed.scheme == "http" and not _loopback(parsed.hostname))
            or (port is not None and not 1 <= port <= 65535)):
        raise ReviewAPIError("base_url 须为无账户、查询参数的 HTTPS 根地址；HTTP 仅用于本机调试")
    if parsed.path.endswith("/responses"):
        raise ReviewAPIError("base_url 请填写接口根地址，不包含 /responses")
    return value


def load_review_config(project_root):
    """Return internal configuration. The returned api_key must never be logged."""
    root = Path(project_root).resolve()
    path = root / LOCAL_CONFIG
    config = dict(DEFAULT_CONFIG)
    if path.is_symlink() or not path.parent.resolve().is_relative_to(root):
        raise ReviewAPIError("本机复核配置须为本仓库中的普通文件")
    if path.exists():
        try:
            if path.stat().st_size > MAX_CONFIG_BYTES:
                raise ReviewAPIError("本机复核配置文件过大")
            with path.open("rb") as source:
                raw = source.read(MAX_CONFIG_BYTES + 1)
            if len(raw) > MAX_CONFIG_BYTES:
                raise ReviewAPIError("本机复核配置文件过大")
            saved = json.loads(raw)
        except (OSError, ValueError, UnicodeError):
            raise ReviewAPIError("无法读取本机复核配置，请检查 JSON 格式和文件权限") from None
        if not isinstance(saved, dict) or set(saved) - set(DEFAULT_CONFIG):
            raise ReviewAPIError("本机复核配置字段无效，请参考 review-api.example.json")
        config.update(saved)
    if config["provider"] != "openai":
        raise ReviewAPIError("复核后端仅支持 openai；本地模型复核已移除，请更新本机配置")
    if not isinstance(config["api_key"], str):
        raise ReviewAPIError("复核配置中的 api_key 必须是字符串")
    config["api_key"] = config["api_key"].strip()
    if any(ord(c) < 33 or ord(c) > 126 for c in config["api_key"]):
        raise ReviewAPIError("复核配置中的 api_key 含有无效字符")
    config["base_url"] = _base_url(config["base_url"])
    if (not isinstance(config["model"], str) or not config["model"].strip()
            or len(config["model"]) > 256 or any(ord(c) < 32 for c in config["model"])):
        raise ReviewAPIError("复核配置中的 model 无效")
    config["model"] = config["model"].strip()
    if not isinstance(config["reasoning_effort"], str) or config["reasoning_effort"] not in EFFORTS:
        raise ReviewAPIError("复核配置中的 reasoning_effort 无效")
    timeout = config["timeout_seconds"]
    if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not 1 <= timeout <= 600 or not math.isfinite(timeout)):
        raise ReviewAPIError("timeout_seconds 须为 1 到 600 秒")
    for name in ("max_output_tokens", "summary_max_output_tokens"):
        _output_budget(config[name], name)
    return config


def _output_budget(value, name):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 16000:
        raise ReviewAPIError(name + " 须为 1 到 16000 的整数")
    return value


def summary_request_config(config):
    """Copy one validated snapshot with the independent summary output budget."""
    snapshot = dict(config)
    snapshot["max_output_tokens"] = _output_budget(
        snapshot.get("summary_max_output_tokens", DEFAULT_CONFIG["summary_max_output_tokens"]),
        "summary_max_output_tokens")
    return snapshot


def _safe_backend(config, project_root, *, connected=False):
    secret = config["api_key"]
    return {
        "ready": bool(secret),
        "configured": bool(secret),
        "connectivity_verified": connected,
        "provider": "openai",
        "model": _redact(config["model"], secret),
        "reasoning_effort": config["reasoning_effort"],
        "max_output_tokens": config["max_output_tokens"],
        "summary_max_output_tokens": config.get("summary_max_output_tokens", DEFAULT_CONFIG["summary_max_output_tokens"]),
        "url": _redact(config["base_url"], secret),
        "config_path": str(Path(project_root).resolve() / LOCAL_CONFIG),
        "label": _redact(f'{config["model"]} · {config["reasoning_effort"]}（API）', secret),
        "transport": "responses",
        "execution": "remote_api",
    }


def review_backend_snapshot(config, project_root):
    """Safe request provenance from the same internal snapshot used to send it."""
    return _safe_backend(config, project_root)


def api_backend_status(project_root):
    """Report configuration only; this function performs no network request."""
    try:
        config = load_review_config(project_root)
        status = _safe_backend(config, project_root)
        if not status["ready"]:
            status["error"] = "复核 API 尚未填写 Key，请编辑 config/review-api.local.json 的 api_key"
        return status
    except ReviewAPIError as exc:
        return {"ready": False, "configured": False, "connectivity_verified": False,
                "provider": "openai", "config_path": str(Path(project_root).resolve() / LOCAL_CONFIG),
                "error": str(exc)}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _usage(value):
    if not isinstance(value, dict):
        return {}
    clean = {}
    for name in ("input_tokens", "output_tokens", "total_tokens"):
        item = value.get(name)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            clean[name] = item
    details = value.get("output_tokens_details")
    if isinstance(details, dict):
        count = details.get("reasoning_tokens")
        if isinstance(count, int) and not isinstance(count, bool) and count >= 0:
            clean["output_tokens_details"] = {"reasoning_tokens": count}
    return clean


def _answer(payload, secret):
    if not isinstance(payload, dict) or payload.get("status") != "completed":
        raise ReviewAPIError("复核 API 响应尚未完整完成，没有生成复核结论")
    if payload.get("error") or payload.get("incomplete_details"):
        raise ReviewAPIError("复核 API 返回未完成或错误状态，没有生成复核结论")
    output = payload.get("output")
    if not isinstance(output, list):
        raise ReviewAPIError("复核 API 返回格式无效，缺少 output 消息")
    parts = []
    for message in output:
        if not isinstance(message, dict) or message.get("type") != "message":
            continue
        if message.get("role") != "assistant":
            continue
        if message.get("status") not in (None, "completed"):
            raise ReviewAPIError("复核 API 消息未完成，没有生成复核结论")
        content = message.get("content")
        if not isinstance(content, list):
            raise ReviewAPIError("复核 API 返回的消息格式无效")
        for item in content:
            if not isinstance(item, dict):
                raise ReviewAPIError("复核 API 返回的消息格式无效")
            if item.get("type") == "refusal":
                raise ReviewAPIError("复核 API 拒绝回答，没有生成复核结论")
            if item.get("type") == "output_text":
                text = item.get("text")
                if not isinstance(text, str):
                    raise ReviewAPIError("复核 API 返回的文本格式无效")
                parts.append(text)
    raw = "\n".join(parts)
    if not raw.strip():
        raise ReviewAPIError("复核 API 没有返回可用文字，没有生成复核结论")
    return _redact(raw, secret)


def request_image_opinion(crop_path, project_root, prompt, *, _config=None):
    """Send only the unannotated crop and fixed question, once, after user action."""
    config = dict(_config) if _config is not None else load_review_config(project_root)
    if config["provider"] != "openai":
        raise ReviewAPIError("当前未选择 API 复核后端")
    if not config["api_key"]:
        raise ReviewAPIError("复核 API 尚未填写 Key，请编辑 config/review-api.local.json 的 api_key")
    started = time.perf_counter()
    try:
        path = Path(crop_path)
        if path.stat().st_size > MAX_CROP_BYTES:
            raise ReviewAPIError("所选头部裁图超过 20MiB，未发送 API 请求")
        with path.open("rb") as source:
            image = source.read(MAX_CROP_BYTES + 1)
    except OSError:
        raise ReviewAPIError("无法读取所选头部裁图，未发送 API 请求") from None
    if len(image) > MAX_CROP_BYTES:
        raise ReviewAPIError("所选头部裁图超过 20MiB，未发送 API 请求")
    if image.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif image.startswith(b"\xff\xd8"):
        mime = "image/jpeg"
    else:
        raise ReviewAPIError("所选头部裁图必须为 PNG 或 JPEG，未发送 API 请求")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ReviewAPIError("复核提示不能为空，未发送 API 请求")
    content = [
        {"type": "input_text", "text": prompt},
        {"type": "input_image", "image_url": "data:" + mime + ";base64," + base64.b64encode(image).decode("ascii"), "detail": "high"},
    ]
    return _request_image_content(content, config, project_root, started)


def request_image_summary(image_paths, project_root, prompt, *, _config=None):
    """Send one to three unannotated summary images in a single request.

    Callers may supply the validated configuration snapshot they already used for
    attempt provenance. This function never rereads that supplied snapshot.
    """
    config = summary_request_config(_config if _config is not None else load_review_config(project_root))
    if config["provider"] != "openai":
        raise ReviewAPIError("当前未选择 API 复核后端")
    if not config["api_key"]:
        raise ReviewAPIError("复核 API 尚未填写 Key，请编辑 config/review-api.local.json 的 api_key")
    if not isinstance(image_paths, (list, tuple)) or not 1 <= len(image_paths) <= 3:
        raise ReviewAPIError("巡查总结须选择 1 到 3 张画面，未发送 API 请求")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ReviewAPIError("巡查总结提示不能为空，未发送 API 请求")
    started = time.perf_counter()
    content = [{"type": "input_text", "text": prompt}]
    total = 0
    for image_path in image_paths:
        try:
            path = Path(image_path)
            if path.stat().st_size > MAX_SUMMARY_IMAGE_BYTES:
                raise ReviewAPIError("巡查总结单张画面超过大小限制，未发送 API 请求")
            with path.open("rb") as source:
                image = source.read(MAX_SUMMARY_IMAGE_BYTES + 1)
        except ReviewAPIError:
            raise
        except (OSError, TypeError, ValueError):
            raise ReviewAPIError("无法读取巡查总结画面，未发送 API 请求") from None
        if len(image) > MAX_SUMMARY_IMAGE_BYTES:
            raise ReviewAPIError("巡查总结单张画面超过大小限制，未发送 API 请求")
        total += len(image)
        if total > MAX_SUMMARY_TOTAL_BYTES:
            raise ReviewAPIError("巡查总结画面总大小超过限制，未发送 API 请求")
        if image.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif image.startswith(b"\xff\xd8"):
            mime = "image/jpeg"
        else:
            raise ReviewAPIError("巡查总结画面必须为 PNG 或 JPEG，未发送 API 请求")
        content.append({"type": "input_image", "image_url": "data:" + mime + ";base64," + base64.b64encode(image).decode("ascii"), "detail": "high"})
    return _request_image_content(content, config, project_root, started)


def _request_image_content(content, config, project_root, started):
    """Shared single-shot Responses transport for head opinions and summaries."""
    payload = {
        "model": config["model"],
        "reasoning": {"effort": config["reasoning_effort"]},
        "store": False,
        "max_output_tokens": config["max_output_tokens"],
        "input": [{"role": "user", "content": content}],
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(config["base_url"] + "/responses", data=data,
                      headers={"Authorization": "Bearer " + config["api_key"],
                               "Content-Type": "application/json", "Accept": "application/json",
                               "User-Agent": "sd1-construction-vision/region-review"}, method="POST")
    handlers = [_NoRedirect()]
    if _loopback(urlsplit(config["base_url"]).hostname):
        handlers.insert(0, ProxyHandler({}))
    opener = build_opener(*handlers)
    try:
        with opener.open(request, timeout=config["timeout_seconds"]) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise ReviewAPIError("复核 API 响应过大，没有生成复核结论")
        try:
            answer = json.loads(body)
        except (ValueError, UnicodeError):
            raise ReviewAPIError("复核 API 未返回有效 JSON，没有生成复核结论") from None
    except HTTPError as exc:
        code = exc.code
        exc.close()
        if 300 <= code < 400:
            raise ReviewAPIError("复核 API 重定向已拒绝，请检查接口根地址") from None
        raise ReviewAPIError(f"复核 API 返回 HTTP {code}，请检查 Key、模型权限或服务额度") from None
    except (TimeoutError, socket.timeout):
        raise ReviewAPIError("复核 API 请求超时，原检测结果保留；没有自动重试") from None
    except ReviewAPIError:
        raise
    except HTTPException:
        raise ReviewAPIError("复核 API 返回无效 HTTP 响应，没有生成复核结论") from None
    except (URLError, OSError, ValueError):
        raise ReviewAPIError("无法连接复核 API，请检查接口地址和网络；没有自动重试") from None
    backend = _safe_backend(config, project_root, connected=True)
    metadata = {}
    for target, source in (("response_id", "id"), ("response_model", "model")):
        value = answer.get(source) if isinstance(answer, dict) else None
        if isinstance(value, str):
            metadata[target] = _redact(value, config["api_key"])[:256]
    try:
        raw = _answer(answer, config["api_key"])
    except ReviewAPIError as exc:
        # A completed HTTP exchange may still be incomplete/refused by the
        # model. Retain only safe provenance, usage and assistant text so a
        # failed summary remains auditable without saving arbitrary payloads.
        parts = []
        if isinstance(answer, dict) and isinstance(answer.get("output"), list):
            for message in answer["output"]:
                if (not isinstance(message, dict) or message.get("type") != "message"
                        or message.get("role") != "assistant" or not isinstance(message.get("content"), list)):
                    continue
                for item in message["content"]:
                    if not isinstance(item, dict):
                        continue
                    value = (item.get("text") if item.get("type") == "output_text" else
                             item.get("refusal") if item.get("type") == "refusal" else None)
                    if isinstance(value, str):
                        parts.append(value)
        exc.evidence = {"backend": backend, "raw_answer": _redact("\n".join(parts), config["api_key"]),
                        "elapsed_seconds": time.perf_counter() - started,
                        "usage": _usage(answer.get("usage")) if isinstance(answer, dict) else {},
                        "api": ["POST /responses"], "fresh_session": True, **metadata}
        raise
    return {"backend": backend, "raw_answer": raw,
            "elapsed_seconds": time.perf_counter() - started,
            "usage": _usage(answer.get("usage")), "api": ["POST /responses"],
            "fresh_session": True, **metadata}
