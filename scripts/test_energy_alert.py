"""电量预警与邮件发送的离线自检。

不联网、不读真实配置，全部依赖注入替身，可直接运行：

    .venv\\Scripts\\python.exe scripts\\test_energy_alert.py
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from zzupy.alerting import (  # noqa: E402
    cooldown_from_env,
    is_dry_run,
    mail_config_from_env,
    readings_from_payload,
    run_energy_alert,
    threshold_from_env,
)
from zzupy.energy import (  # noqa: E402
    AlertState,
    EnergyAlertError,
    MeterReading,
    decide_notification,
    evaluate,
    format_alert_html,
    format_alert_message,
    parse_threshold,
    record_notification,
)
from zzupy.mail import (  # noqa: E402
    MailConfig,
    MailConfigError,
    MailMessage,
    MailResult,
    MailSendError,
    send_mail,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: object = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text or (str(payload) if payload is not None else "")

    def json(self) -> object:
        if self._payload is None:
            raise ValueError("no json body")
        return self._payload


class FakeClient:
    """记录每次请求的最小 httpx2.Client 替身。"""

    def __init__(self, *responses: FakeResponse):
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def post(self, url, *, headers=None, json=None):
        self.calls.append({"url": url, "headers": dict(headers or {}), "json": json})
        if not self._responses:
            raise AssertionError("FakeClient 的响应已经用完了")
        return self._responses.pop(0)

    def close(self) -> None:
        self.closed = True


def _config(**overrides) -> MailConfig:
    values = {
        "provider": "resend",
        "api_key": "re_test_key",
        "sender": "alert@example.com",
        "recipients": ("me@example.com",),
    }
    values.update(overrides)
    return MailConfig(**values)  # type: ignore[arg-type]


def test_threshold_parsing() -> None:
    assert parse_threshold(None) == 2.0
    assert parse_threshold("") == 2.0
    assert parse_threshold("2") == 2.0
    assert parse_threshold(0.5) == 0.5
    for bad in ("abc", -1):
        try:
            parse_threshold(bad)
        except Exception as exc:
            assert "阈值" in str(exc), exc
        else:
            raise AssertionError(f"阈值 {bad!r} 应该被拒绝")


def test_evaluate_picks_lowest_ok_meter() -> None:
    readings = [
        MeterReading(label="照明", meter_id="a", remaining=18.5),
        MeterReading(label="空调", meter_id="b", remaining=1.25),
        MeterReading(label="坏表", meter_id="c", error="接口超时"),
    ]
    decision = evaluate(readings, 2.0)
    assert decision.low is True
    assert decision.lowest == 1.25
    assert decision.low_label == "空调"
    assert decision.should_notify is True

    # 全部读取失败时不应该误报低电量。
    broken = evaluate([MeterReading(label="照明", meter_id="a", error="超时")], 2.0)
    assert broken.low is False
    assert broken.lowest is None
    assert broken.should_notify is False

    # 高于阈值时也不提醒。
    fine = evaluate([MeterReading(label="照明", meter_id="a", remaining=9.0)], 2.0)
    assert fine.low is False
    assert "高于阈值" in fine.reason

    # 恰好等于阈值算低电量。
    assert evaluate([MeterReading(label="照明", meter_id="a", remaining=2.0)], 2.0).low


def test_dedup_and_rearm(tmp: Path) -> None:
    state = AlertState(tmp / "state.json")
    readings = [MeterReading(label="空调", meter_id="b", remaining=1.0)]
    decision = evaluate(readings, 2.0)

    # 第一次进入低电量：应该发信。
    first = decide_notification(decision, state, now=1_000.0)
    assert first.should_notify is True
    record_notification(state, now=1_000.0)

    # 仍然低电量且未到冷却时间：不再发信。
    second = decide_notification(decision, state, now=1_100.0)
    assert second.should_notify is False
    assert "已提醒过" in second.reason

    # 冷却时间到了：补发一次。
    third = decide_notification(decision, state, now=1_000.0 + 12 * 3600)
    assert third.should_notify is True

    # 电量回升：重新武装，状态落盘。
    recovered = evaluate([MeterReading(label="空调", meter_id="b", remaining=30.0)], 2.0)
    assert decide_notification(recovered, state, now=2_000.0).should_notify is False
    assert state.load()["alerted"] is False

    # 再次变低：重新提醒，说明去重状态确实复位了。
    assert decide_notification(decision, state, now=2_100.0).should_notify is True


def test_state_is_shared_between_instances(tmp: Path) -> None:
    path = tmp / "shared.json"
    first = AlertState(path)
    reading = [MeterReading(label="照明", meter_id="a", remaining=0.5)]
    record_notification(first, now=500.0)

    # 模拟另一个进程重新读盘，应该看到同样的去重状态。
    second = AlertState(path)
    decided = decide_notification(evaluate(reading, 2.0), second, now=600.0)
    assert decided.should_notify is False


def test_alert_message_content() -> None:
    readings = [
        MeterReading(label="照明", meter_id="a", remaining=1.5),
        MeterReading(label="空调", meter_id="b", error="接口超时"),
    ]
    decision = evaluate(readings, 2.0)
    subject, body = format_alert_message(decision, room="7-2--186-8511", readings=readings)
    assert "电量预警" in subject
    assert "1.5" in subject
    assert "7-2--186-8511" in body
    assert "读取失败" in body
    assert "照明" in body

    html = format_alert_html(decision, room="7-2--186-8511", readings=readings)
    assert html.startswith("<!doctype html>")
    assert "寝室电量偏低" in html
    assert "1.5 度" in html


def test_resend_payload_and_headers() -> None:
    client = FakeClient(FakeResponse(200, {"id": "abc-123"}))
    result = send_mail(
        _config(),
        MailMessage(subject="测试", text="正文"),
        client=client,  # type: ignore[arg-type]
    )
    assert result.provider == "resend"
    assert result.message_id == "abc-123"
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["url"] == "https://api.resend.com/emails"
    assert call["headers"]["Authorization"] == "Bearer re_test_key"
    payload = call["json"]
    assert payload["from"] == "郑大生活助手 <alert@example.com>"
    assert payload["to"] == ["me@example.com"]
    assert payload["text"] == "正文"
    assert "html" not in payload
    # 调用方传入的 client 不应该被关闭。
    assert client.closed is False


def test_brevo_payload_shape() -> None:
    client = FakeClient(FakeResponse(201, {"messageId": "<x@relay>"}))
    result = send_mail(
        _config(provider="brevo", api_key="xkeysib-test"),
        MailMessage(subject="测试", text="正文", html="<p>正文</p>"),
        client=client,  # type: ignore[arg-type]
    )
    assert result.message_id == "<x@relay>"
    call = client.calls[0]
    assert call["url"] == "https://api.brevo.com/v3/smtp/email"
    assert call["headers"]["api-key"] == "xkeysib-test"
    payload = call["json"]
    assert payload["sender"] == {"email": "alert@example.com", "name": "郑大生活助手"}
    assert payload["to"] == [{"email": "me@example.com"}]
    assert payload["htmlContent"] == "<p>正文</p>"


def test_fallback_provider_on_retryable_error() -> None:
    client = FakeClient(
        FakeResponse(500, text="upstream down"),
        FakeResponse(200, {"messageId": "ok-2"}),
    )
    result = send_mail(
        _config(provider="resend", fallback_provider="brevo", fallback_api_key="bk"),
        MailMessage(subject="测试", text="正文"),
        client=client,  # type: ignore[arg-type]
    )
    assert result.provider == "brevo"
    assert result.message_id == "ok-2"
    assert len(result.attempts) == 1
    assert result.attempts[0]["status_code"] == 500


def test_fatal_error_does_not_fall_back() -> None:
    client = FakeClient(FakeResponse(401, text="invalid api key"))
    try:
        send_mail(
            _config(fallback_provider="brevo", fallback_api_key="bk"),
            MailMessage(subject="测试", text="正文"),
            client=client,  # type: ignore[arg-type]
        )
    except MailSendError as exc:
        assert exc.context["status_code"] == 401
    else:
        raise AssertionError("401 应该直接抛出，不应改用备用服务商")
    # 只尝试了主服务商一次。
    assert len(client.calls) == 1


def test_config_validation() -> None:
    cases = [
        _config(api_key=""),
        _config(sender="not-an-email"),
        _config(recipients=()),
        _config(recipients=("bad",)),
        _config(provider="sendgrid"),  # type: ignore[arg-type]
        _config(fallback_provider="brevo", fallback_api_key=""),
    ]
    for config in cases:
        try:
            config.validate()
        except MailConfigError as exc:
            assert str(exc), exc
        else:
            raise AssertionError(f"配置 {config} 应该校验失败")

    try:
        MailMessage(subject="  ", text="正文")
    except MailConfigError:
        pass
    else:
        raise AssertionError("空主题应该被拒绝")

    try:
        MailMessage(subject="主题", text="   ")
    except MailConfigError:
        pass
    else:
        raise AssertionError("空正文应该被拒绝")


def test_alerting_config_from_env() -> None:
    config = mail_config_from_env(
        {
            "ZZU_MAIL_PROVIDER": "brevo",
            "ZZU_MAIL_API_KEY": "xkeysib-1",
            "ZZU_MAIL_FROM": "alert@example.com",
            "ZZU_MAIL_TO": "a@example.com, b@example.com;c@example.com",
            "ZZU_MAIL_FROM_NAME": "助手",
        }
    )
    assert config.provider == "brevo"
    assert config.sender == "alert@example.com"
    assert config.sender_name == "助手"
    assert config.recipients == (
        "a@example.com",
        "b@example.com",
        "c@example.com",
    )

    # 缺少必填项时要报出具体缺了哪些。
    try:
        mail_config_from_env({"ZZU_MAIL_PROVIDER": "resend"})
    except MailConfigError as exc:
        assert "ZZU_MAIL_API_KEY" in str(exc), exc
        assert "ZZU_MAIL_TO" in str(exc), exc
    else:
        raise AssertionError("空配置应该报错")

    assert threshold_from_env({"ZZU_ENERGY_THRESHOLD": "2.5"}) == 2.5
    assert threshold_from_env({}) == 2.0
    assert cooldown_from_env({}) == 12 * 3600
    assert cooldown_from_env({"ZZU_ENERGY_COOLDOWN_SECONDS": "0"}) == 0
    assert is_dry_run({"ZZU_ALERT_DRY_RUN": "1"}) is True
    assert is_dry_run({}) is False


def test_readings_from_payload() -> None:
    readings = readings_from_payload(
        [
            {"label": "照明", "meter_id": "a", "remaining": 1.5},
            {"label": "空调", "meter_id": "b", "error": "接口超时"},
        ]
    )
    assert readings[0].ok is True
    assert readings[0].remaining == 1.5
    assert readings[1].ok is False
    assert readings[1].error == "接口超时"

    for bad in ("不是列表", [1, 2], {"label": "x"}):
        try:
            readings_from_payload(bad)
        except EnergyAlertError:
            pass
        else:
            raise AssertionError(f"{bad!r} 应该被拒绝")


def test_run_energy_alert_dedup_and_dry_run(scratch: Path) -> None:
    env = {
        "ZZU_MAIL_PROVIDER": "resend",
        "ZZU_MAIL_API_KEY": "re_test",
        "ZZU_MAIL_FROM": "alert@example.com",
        "ZZU_MAIL_TO": "me@example.com",
        "ZZU_ENERGY_STATE": str(scratch / "run.json"),
        "ZZU_ENERGY_THRESHOLD": "2",
    }
    readings = [MeterReading(label="空调", meter_id="b", remaining=1.0)]

    # 第一次低电量：真正发信。
    client = FakeClient(FakeResponse(200, {"id": "m-1"}))
    result = run_energy_alert(readings, room="7-2--186-8511", env=env, client=client)
    assert result.mail is not None
    assert result.mail.provider == "resend"
    assert result.decision.should_notify is True
    assert len(client.calls) == 1
    payload = client.calls[0]["json"]
    assert "7-2--186-8511" in payload["subject"]

    # 第二次：状态已落盘，应该跳过发信且不再调用接口。
    second_client = FakeClient()
    again = run_energy_alert(
        readings, room="7-2--186-8511", env=env, client=second_client
    )
    assert again.mail is None
    assert again.deduplicated is True
    assert second_client.calls == []

    # 电量回升后再变低：重新提醒。
    high = [MeterReading(label="空调", meter_id="b", remaining=40.0)]
    recovered = run_energy_alert(high, env=env, client=FakeClient())
    assert recovered.mail is None
    assert recovered.decision.low is False
    third_client = FakeClient(FakeResponse(200, {"id": "m-3"}))
    relapsed = run_energy_alert(readings, env=env, client=third_client)
    assert relapsed.mail is not None

    # 试跑模式：只判断不发信，也不写去重状态。
    dry_env = {**env, "ZZU_ALERT_DRY_RUN": "1", "ZZU_ENERGY_STATE": str(scratch / "dry.json")}
    dry_client = FakeClient()
    dry = run_energy_alert(readings, env=dry_env, client=dry_client)
    assert dry.mail is None
    assert dry.decision.low is True
    assert dry_client.calls == []


def test_api_endpoint_end_to_end(scratch: Path) -> None:
    """用 FastAPI TestClient 真跑一遍接口，在发信边界替换掉真实网络调用。"""
    try:
        from fastapi.testclient import TestClient
    except ImportError:
        print("  (跳过接口测试：当前环境没有 fastapi.testclient)")
        return

    import api.index as api_module
    import zzupy.alerting as alerting

    captured: list[dict] = []
    original_send = alerting.send_mail

    def fake_send(config, message, *, client=None):  # type: ignore[no-untyped-def]
        captured.append(
            {
                "provider": config.provider,
                "from": config.sender,
                "to": list(config.recipients),
                "subject": message.subject,
                "text": message.text,
            }
        )
        return MailResult(
            provider=config.provider,
            message_id=f"api-{len(captured)}",
        )

    os.environ.update(
        {
            "ZZU_MAIL_PROVIDER": "resend",
            "ZZU_MAIL_API_KEY": "re_test",
            "ZZU_MAIL_FROM": "alert@example.com",
            "ZZU_MAIL_TO": "me@example.com",
            "ZZU_ALERT_SECRET": "s3cret",
            "ZZU_ENERGY_STATE": str(scratch / "api.json"),
            "ZZU_ENERGY_THRESHOLD": "2",
        }
    )
    alerting.send_mail = fake_send  # type: ignore[assignment]
    try:
        client = TestClient(api_module.app)

        # 空 meters 触发请求体校验
        assert client.post("/api/energy-alert", json={"meters": []}).status_code == 422

        # 缺少密钥 -> 401
        no_secret = client.post(
            "/api/energy-alert",
            json={"meters": [{"label": "空调", "remaining": 1.0}]},
        )
        assert no_secret.status_code == 401, no_secret.text

        # 密钥错误 -> 401
        wrong = client.post(
            "/api/energy-alert",
            json={"meters": [{"label": "空调", "remaining": 1.0}]},
            headers={"x-zzu-alert-secret": "nope"},
        )
        assert wrong.status_code == 401, wrong.text

        # 未配置账号密码的巡检接口 -> 503，并说明原因
        cron = client.get(
            "/api/energy-alert/cron", headers={"x-zzu-alert-secret": "s3cret"}
        )
        assert cron.status_code == 503, cron.text
        assert "ZZU_ACCOUNT" in cron.json()["detail"]

        # 正常上报 -> 发信
        body = {
            "meters": [
                {"label": "照明", "meter_id": "a", "remaining": 12.0},
                {"label": "空调", "meter_id": "b", "remaining": 1.25},
            ],
            "room": "7-2--186-8511",
        }
        ok = client.post(
            "/api/energy-alert", json=body, headers={"x-zzu-alert-secret": "s3cret"}
        )
        assert ok.status_code == 200, ok.text
        data = ok.json()
        assert data["notified"] is True
        assert data["low"] is True
        assert data["lowest"] == 1.25
        assert data["provider"] == "resend"
        assert len(captured) == 1
        assert "7-2--186-8511" in captured[0]["subject"]
        assert captured[0]["to"] == ["me@example.com"]

        # 重复上报 -> 去重，不再发信
        again = client.post(
            "/api/energy-alert", json=body, headers={"x-zzu-alert-secret": "s3cret"}
        )
        assert again.status_code == 200, again.text
        assert again.json()["notified"] is False
        assert again.json()["deduplicated"] is True
        assert len(captured) == 1

        # 查询参数形式的密钥也应该被接受（方便外部定时器配置）
        via_query = client.post(
            "/api/energy-alert?secret=s3cret",
            json={
                "meters": [{"label": "照明", "remaining": 30.0}],
                "room": "7-2--186-8511",
            },
        )
        assert via_query.status_code == 200, via_query.text
        assert via_query.json()["low"] is False
    finally:
        alerting.send_mail = original_send  # type: ignore[assignment]


def _scratch_directory() -> Path:
    """返回一个可写的临时目录。"""
    import tempfile

    return Path(tempfile.mkdtemp(prefix="zzu-energy-alert-"))


def main() -> None:
    scratch = _scratch_directory()
    original_env = dict(os.environ)
    try:
        test_threshold_parsing()
        test_evaluate_picks_lowest_ok_meter()
        test_dedup_and_rearm(scratch)
        test_state_is_shared_between_instances(scratch)
        test_alert_message_content()
        test_resend_payload_and_headers()
        test_brevo_payload_shape()
        test_fallback_provider_on_retryable_error()
        test_fatal_error_does_not_fall_back()
        test_config_validation()
        test_alerting_config_from_env()
        test_readings_from_payload()
        test_run_energy_alert_dedup_and_dry_run(scratch)
        test_api_endpoint_end_to_end(scratch)
    finally:
        os.environ.clear()
        os.environ.update(original_env)
        shutil.rmtree(scratch, ignore_errors=True)
    print("电量预警与邮件发送自检全部通过。")


if __name__ == "__main__":
    main()
