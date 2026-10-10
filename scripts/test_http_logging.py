"""HTTP 日志钩子的健壮性自检。

回归背景：重定向链里 ``response.request`` 可能是尚未 read() 的流式请求，此时
访问 ``request.content`` 会抛 ``httpx2.RequestNotRead``。日志钩子必须容忍这种
情况，否则一个纯日志功能会让业务请求直接失败。

    .venv\\Scripts\\python.exe scripts\\test_http_logging.py
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx2  # noqa: E402

from zzupy.logging import (  # noqa: E402
    build_http_event_hooks,
    sanitize_http_body,
    sanitize_http_url,
)


def test_sanitize_url_redacts_sensitive_params() -> None:
    url = "https://example.com/api?token=secret&page=2&password=123"
    cleaned = sanitize_http_url(url)
    assert "secret" not in cleaned
    assert "123" not in cleaned
    assert "page=2" in cleaned


def test_sanitize_body_redacts_sensitive_keys() -> None:
    body = sanitize_http_body(
        '{"userName": "someone", "password": "hunter2", "page": 1}',
        content_type="application/json",
    )
    assert "hunter2" not in body
    assert "someone" not in body
    assert "REDACTED" in body


def test_sanitize_body_handles_form_and_binary() -> None:
    form = sanitize_http_body(
        "username=abc&password=xyz",
        content_type="application/x-www-form-urlencoded",
    )
    assert "xyz" not in form
    assert sanitize_http_body(b"\x00\x01\xff", content_type="image/png") == "(binary)"
    assert sanitize_http_body(None) == ""
    assert sanitize_http_body("") == ""


def test_logging_hook_survives_streaming_request() -> None:
    """核心回归：未 read() 的请求不应让钩子抛异常。

    httpx2 的 ``Request.content`` 在缺少 ``_content`` 时（即尚未 ``read()``，
    重定向链里就会这样）抛 ``RequestNotRead``。这里精确构造该状态。
    """
    request = httpx2.Request("POST", "https://example.com/api", json={"a": 1})
    del request.__dict__["_content"]

    try:
        request.content
    except httpx2.RequestNotRead:
        pass
    else:
        raise AssertionError("前置条件不成立：content 竟然可以读取")

    hooks = build_http_event_hooks()
    for hook in hooks["request"]:
        hook(request)  # 修复前这里会抛 RequestNotRead
    for hook in hooks["response"]:
        hook(
            httpx2.Response(
                200, request=request, json={"ok": True}
            )
        )


def test_logging_hook_logs_normal_request() -> None:
    request = httpx2.Request("POST", "https://example.com/api", json={"a": 1})
    hooks = build_http_event_hooks()
    for hook in hooks["request"]:
        hook(request)
    assert request.content  # 普通请求仍能正常读到内容


def test_hooks_work_end_to_end() -> None:
    """用本地 ASGI 传输跑一次真实请求，确认钩子不影响正常收发。"""
    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/redirect":
            return httpx2.Response(302, headers={"location": "https://test/api"})
        return httpx2.Response(200, json={"ok": True})

    transport = httpx2.MockTransport(handler)
    client = httpx2.Client(
        transport=transport,
        event_hooks=build_http_event_hooks(),
        follow_redirects=True,
        headers={"Authorization": "secret-token"},
    )
    response = client.post("https://test/redirect", json={"a": 1})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    client.close()


def test_async_hooks_exist() -> None:
    hooks = build_http_event_hooks(async_client=True)
    assert set(hooks) == {"request", "response"}
    assert len(hooks["request"]) == 1


def main() -> None:
    test_sanitize_url_redacts_sensitive_params()
    test_sanitize_body_redacts_sensitive_keys()
    test_sanitize_body_handles_form_and_binary()
    test_logging_hook_survives_streaming_request()
    test_logging_hook_logs_normal_request()
    test_hooks_work_end_to_end()
    test_async_hooks_exist()
    print("HTTP 日志钩子健壮性自检全部通过（含流式请求回归）。")


if __name__ == "__main__":
    main()
