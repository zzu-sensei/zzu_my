"""电量预警的编排逻辑。

把「读配置 → 查电量 → 判断阈值 → 去重 → 发邮件」串成一个可复用流程，
供 Vercel 后端、命令行常驻巡检与桌面端共用。所有配置都来自环境变量，
不把任何凭据写进代码或仓库。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Mapping

from zzupy.energy import (
    DEFAULT_COOLDOWN_SECONDS,
    STATE_ENV_VAR,
    AlertDecision,
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
from zzupy.logging import logger
from zzupy.mail import (
    MailConfig,
    MailConfigError,
    MailMessage,
    MailResult,
    send_mail,
)

#: 读配置时使用的环境变量名。
PROVIDER_ENV: Final = "ZZU_MAIL_PROVIDER"
API_KEY_ENV: Final = "ZZU_MAIL_API_KEY"
FALLBACK_PROVIDER_ENV: Final = "ZZU_MAIL_FALLBACK_PROVIDER"
FALLBACK_API_KEY_ENV: Final = "ZZU_MAIL_FALLBACK_API_KEY"
MAIL_FROM_ENV: Final = "ZZU_MAIL_FROM"
MAIL_FROM_NAME_ENV: Final = "ZZU_MAIL_FROM_NAME"
MAIL_TO_ENV: Final = "ZZU_MAIL_TO"
DRY_RUN_ENV: Final = "ZZU_ALERT_DRY_RUN"

#: 保护巡检/发信接口的共享密钥。没配置时接口一律拒绝，避免被匿名刷爆额度。
SECRET_ENV: Final = "ZZU_ALERT_SECRET"

#: 服务端巡检所需的一卡通凭据。仅在让服务端自己查电量时才需要。
ACCOUNT_ENV: Final = "ZZU_ACCOUNT"
PASSWORD_ENV: Final = "ZZU_PASSWORD"

#: 允许在邮件配置缺失时只记录日志而不发信，便于本地试跑。
DEFAULT_PROVIDER: Final = "resend"


def _split_addresses(raw: str) -> tuple[str, ...]:
    """把逗号、分号或空白分隔的地址串拆成元组。"""
    normalized = raw.replace(";", ",").replace("\n", ",")
    return tuple(part.strip() for part in normalized.split(",") if part.strip())


@dataclass(frozen=True)
class AlertRunResult:
    """一次电量预警检查的结果。

    Args:
        decision: 阈值判断与去重后的最终结论。
        readings: 本次读到的各电表读数。
        room: 被检查的寝室 ID。
        mail: 实际发出的邮件结果；未发信时为 ``None``。
        deduplicated: 是否因为已经提醒过而跳过了发信。
    """

    decision: AlertDecision
    readings: tuple[MeterReading, ...]
    room: str = ""
    mail: MailResult | None = None
    deduplicated: bool = False

    def to_dict(self) -> dict[str, Any]:
        """转换为便于 JSON 序列化的字典。"""
        return {
            "low": self.decision.low,
            "threshold": self.decision.threshold,
            "lowest": self.decision.lowest,
            "low_label": self.decision.low_label,
            "notified": self.mail is not None,
            "deduplicated": self.deduplicated,
            "reason": self.decision.reason,
            "room": self.room,
            "provider": self.mail.provider if self.mail else None,
            "message_id": self.mail.message_id if self.mail else None,
            "meters": [
                {
                    "label": item.label,
                    "meter_id": item.meter_id,
                    "remaining": item.remaining,
                    "error": item.error,
                }
                for item in self.readings
            ],
        }


def mail_config_from_env(env: Mapping[str, str] | None = None) -> MailConfig:
    """从环境变量构造邮件配置。

    Raises:
        MailConfigError: 缺少必填项，或配置了未知服务商。
    """
    values = os.environ if env is None else env

    provider = (values.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip().lower()
    sender = (values.get(MAIL_FROM_ENV) or "").strip()
    recipients = _split_addresses(values.get(MAIL_TO_ENV) or "")

    missing = [
        name
        for name, value in (
            (API_KEY_ENV, values.get(API_KEY_ENV)),
            (MAIL_FROM_ENV, sender),
            (MAIL_TO_ENV, recipients),
        )
        if not value
    ]
    if missing:
        raise MailConfigError(
            f"缺少邮件配置：{'、'.join(missing)}",
            context={"missing": missing},
        )

    fallback_provider = (values.get(FALLBACK_PROVIDER_ENV) or "").strip().lower()
    return MailConfig(
        provider=provider,  # type: ignore[arg-type]
        api_key=(values.get(API_KEY_ENV) or "").strip(),
        sender=sender,
        recipients=recipients,
        sender_name=(
            values.get(MAIL_FROM_NAME_ENV) or "郑大生活助手"
        ).strip(),
        fallback_provider=fallback_provider or None,  # type: ignore[arg-type]
        fallback_api_key=(values.get(FALLBACK_API_KEY_ENV) or "").strip(),
    )


def threshold_from_env(env: Mapping[str, str] | None = None) -> float:
    """从环境变量读取预警阈值。"""
    values = os.environ if env is None else env
    return parse_threshold(values.get("ZZU_ENERGY_THRESHOLD"))


def cooldown_from_env(env: Mapping[str, str] | None = None) -> int:
    """从环境变量读取防打扰冷却时间（秒）。"""
    values = os.environ if env is None else env
    raw = values.get("ZZU_ENERGY_COOLDOWN_SECONDS")
    if not raw:
        return DEFAULT_COOLDOWN_SECONDS
    try:
        return max(0, int(raw))
    except (TypeError, ValueError) as exc:
        raise EnergyAlertError(
            f"冷却时间不是合法整数：{raw!r}",
            context={"value": raw},
        ) from exc


def is_dry_run(env: Mapping[str, str] | None = None) -> bool:
    """是否处于只判断不发信的试跑模式。"""
    values = os.environ if env is None else env
    return (values.get(DRY_RUN_ENV) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def readings_from_payload(meters: Any) -> list[MeterReading]:
    """把接口返回的 ``meter_list`` 归一化成读数列表。

    既接受 ``{"label": ..., "meter_id": ..., "remaining": ...}`` 这种结构，
    也接受 ``discover_meter_energy`` 返回的带 ``error`` 的条目。

    Raises:
        EnergyAlertError: 入参不是列表，或条目缺少必要字段。
    """
    if not isinstance(meters, list):
        raise EnergyAlertError(
            "meter_list 必须是数组",
            context={"type": type(meters).__name__},
        )

    readings: list[MeterReading] = []
    for index, item in enumerate(meters):
        if not isinstance(item, Mapping):
            raise EnergyAlertError(
                f"meter_list[{index}] 必须是对象",
                context={"index": index},
            )
        remaining = item.get("remaining")
        error = item.get("error")
        readings.append(
            MeterReading(
                label=str(item.get("label") or f"电表{index + 1}"),
                meter_id=str(item.get("meter_id") or ""),
                remaining=None if remaining is None else float(remaining),
                error=None if error is None else str(error),
            )
        )
    return readings


def read_room_readings(
    ecard: Any,
    room: str = "",
    *,
    history: Any = None,
) -> tuple[str, list[MeterReading]]:
    """通过 ``ECardClient`` 读取照明与空调电表的剩余电量。

    Args:
        ecard: 已登录的 ``ECardClient``。
        room: 指定寝室 ID；留空表示使用账号默认寝室。
        history: 可选的耗电历史。传入时会把本次读数记录下来，供后续估算
            耗电速度使用。

    Returns:
        ``(默认寝室 ID, 读数列表)`` 二元组。单个电表读取失败不会中断整体，
        而是记录为该条目的 ``error``。
    """
    default_room = room or ecard.get_default_room()
    readings: list[MeterReading] = []
    for meter_type in ("照明", "空调"):
        try:
            _source, meter_id, remaining = ecard.get_meter_energy(meter_type)
        except Exception as exc:  # noqa: BLE001 - 单个电表失败不应影响整体
            logger.warning("读取{}电表失败：{}", meter_type, exc)
            readings.append(
                MeterReading(
                    label=meter_type,
                    meter_id="",
                    error=str(exc),
                )
            )
            continue
        readings.append(
            MeterReading(
                label=meter_type,
                meter_id=meter_id,
                remaining=float(remaining),
            )
        )

    if history is not None:
        try:
            written = history.record(readings)
            logger.debug("已记录 {} 条电量采样", written)
        except Exception as exc:  # noqa: BLE001 - 采样失败不应影响查询结果
            logger.warning("记录电量采样失败：{}", exc)
    return default_room, readings


def build_message(
    decision: AlertDecision,
    readings: list[MeterReading],
    room: str = "",
) -> MailMessage:
    """根据判断结果构造提醒邮件。"""
    subject, text = format_alert_message(decision, room=room, readings=readings)
    return MailMessage(
        subject=subject,
        text=text,
        html=format_alert_html(decision, room=room, readings=readings),
    )


def run_energy_alert(
    readings: list[MeterReading],
    *,
    room: str = "",
    threshold: float | None = None,
    cooldown_seconds: int | None = None,
    state: AlertState | None = None,
    env: Mapping[str, str] | None = None,
    client: Any = None,
) -> AlertRunResult:
    """执行一次完整的电量预警检查，必要时发信。

    Args:
        readings: 各电表读数。
        room: 寝室 ID，仅用于邮件文案。
        threshold: 预警阈值；为 ``None`` 时读环境变量。
        cooldown_seconds: 防打扰冷却时间；为 ``None`` 时读环境变量。
        state: 去重状态；为 ``None`` 时使用默认状态文件。
        env: 环境变量映射，便于测试注入。
        client: 可选的 ``httpx2.Client``，透传给发信模块。

    Returns:
        检查结果。``mail`` 非空表示确实发出了邮件。

    Raises:
        MailConfigError: 邮件配置缺失（试跑模式下不触发）。
        MailSendError: 发信失败。
        EnergyAlertError: 阈值或冷却时间非法。
    """
    values = os.environ if env is None else env
    active_threshold = (
        threshold_from_env(values) if threshold is None else threshold
    )
    active_cooldown = (
        cooldown_from_env(values) if cooldown_seconds is None else cooldown_seconds
    )
    # 状态路径同样要走传入的 env，否则测试或不同部署之间会互相串状态。
    active_state = (
        state
        if state is not None
        else AlertState(Path(values[STATE_ENV_VAR]) if values.get(STATE_ENV_VAR) else None)
    )

    decision = evaluate(readings, active_threshold)
    decided = decide_notification(
        decision,
        active_state,
        cooldown_seconds=active_cooldown,
    )

    if not decided.should_notify:
        logger.debug("本次无需提醒：{}", decided.reason or "电量正常")
        return AlertRunResult(
            decision=decided,
            readings=tuple(readings),
            room=room,
            deduplicated=decision.low and not decided.should_notify,
        )

    if is_dry_run(values):
        logger.info("试跑模式：跳过发信，仅记录判断结果")
        return AlertRunResult(
            decision=decided,
            readings=tuple(readings),
            room=room,
        )

    message = build_message(decided, readings, room)
    config = mail_config_from_env(values)
    result = send_mail(config, message, client=client)

    # 只有确实发信成功才记录去重状态，避免发送失败后彻底静默。
    record_notification(active_state)
    logger.info("低电量提醒已发送：{}", message.subject)
    return AlertRunResult(
        decision=decided,
        readings=tuple(readings),
        room=room,
        mail=result,
    )


__all__ = [
    "ACCOUNT_ENV",
    "API_KEY_ENV",
    "AlertRunResult",
    "DEFAULT_PROVIDER",
    "DRY_RUN_ENV",
    "FALLBACK_API_KEY_ENV",
    "FALLBACK_PROVIDER_ENV",
    "MAIL_FROM_ENV",
    "MAIL_FROM_NAME_ENV",
    "MAIL_TO_ENV",
    "PASSWORD_ENV",
    "PROVIDER_ENV",
    "SECRET_ENV",
    "build_message",
    "cooldown_from_env",
    "is_dry_run",
    "mail_config_from_env",
    "read_room_readings",
    "readings_from_payload",
    "run_energy_alert",
    "threshold_from_env",
]
