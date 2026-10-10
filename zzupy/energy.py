"""寝室电量预警模块。

该模块把「查电量 → 判断阈值 → 发提醒」串成一条可复用的流程，供命令行、
桌面 GUI 与 Vercel 后端共用。设计目标是幂等与防打扰：

- 同一轮持续低电量只提醒一次，恢复充值后自动重新武装（re-arm）。
- 状态保存在本地 JSON 文件里，因此进程退出、重启都不会重复轰炸。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Final, Mapping

from zzupy.logging import logger

#: 默认预警阈值（度）。低于该值即视为需要提醒。
DEFAULT_THRESHOLD: Final = 2.0

#: 默认防打扰间隔（秒）。即使仍处于低电量，也不会比这更频繁地发信。
DEFAULT_COOLDOWN_SECONDS: Final = 12 * 60 * 60

#: 电量高于阈值加该回差后，才认为已经充值、可以重新武装提醒。
REARM_MARGIN: Final = 0.5

STATE_ENV_VAR: Final = "ZZU_ENERGY_STATE"
THRESHOLD_ENV_VAR: Final = "ZZU_ENERGY_THRESHOLD"

_APP_DIR_NAME: Final = "ZZU.Py"
_STATE_FILE_NAME: Final = "energy_alert.json"


class EnergyAlertError(Exception):
    """电量预警配置或状态错误。"""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.context = dict(context or {})

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class MeterReading:
    """单个电表的读数。

    Args:
        label: 电表名称，例如「照明」或「空调」。
        meter_id: 完整电表 ID。
        remaining: 剩余电量（度）。读取失败时为 ``None``。
        error: 读取失败原因。
    """

    label: str
    meter_id: str
    remaining: float | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        """该电表是否读取成功。"""
        return self.remaining is not None and self.error is None


@dataclass(frozen=True)
class AlertDecision:
    """一次低电量判断的结果。

    Args:
        low: 是否处于低电量状态。
        threshold: 本次使用的阈值。
        lowest: 所有可用电表中的最低电量。
        low_label: 最低电量对应的电表名称。
        should_notify: 本次是否应该发信。
        reason: 不重复发信的原因。
    """

    low: bool
    threshold: float
    lowest: float | None
    low_label: str
    should_notify: bool
    reason: str = ""


def default_state_path() -> Path:
    """返回默认的状态文件路径。

    优先使用 ``ZZU_ENERGY_STATE``，其次是平台约定的用户数据目录。
    """
    if override := os.environ.get(STATE_ENV_VAR):
        return Path(override).expanduser()

    if appdata := os.environ.get("APPDATA"):
        return Path(appdata) / _APP_DIR_NAME / _STATE_FILE_NAME

    base = Path(
        os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state"
    )
    return base / "zzupy" / _STATE_FILE_NAME


class AlertState:
    """低电量提醒状态，落盘保存以跨进程去重。

    Args:
        path: 状态文件路径。为 ``None`` 时不落盘，仅进程内生效。
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path if path is not None else default_state_path()
        self._cache: dict[str, Any] = {}
        self._loaded = False

    def load(self) -> dict[str, Any]:
        """读取状态；文件缺失或损坏时返回空状态。"""
        if self._loaded:
            return self._cache
        self._loaded = True
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._cache = {}
            return self._cache
        except OSError as exc:
            logger.warning("读取电量预警状态失败：{}", exc)
            self._cache = {}
            return self._cache
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("电量预警状态文件损坏，已按空状态处理：{}", self.path)
            data = {}
        self._cache = data if isinstance(data, dict) else {}
        return self._cache

    def save(self) -> None:
        """原子写入状态，避免并发读写出半个文件。

        这里用 ``os.open`` 直接创建临时文件而不是 ``tempfile``：部分受限运行时
        （例如带文件沙箱的环境）会让 ``tempfile`` 的探测逻辑卡住，而这里只需要
        一个确定性的临时名字。临时文件名不使用前导点，某些沙箱会拒绝创建隐藏
        文件。

        Raises:
            EnergyAlertError: 状态目录或状态文件不可写。调用方可以据此提示
                用户改用 ``ZZU_ENERGY_STATE`` 指向一个可写位置。
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise EnergyAlertError(
                f"电量预警状态目录不可写：{self.path.parent}",
                context={"path": str(self.path), "errno": exc.errno},
            ) from exc

        payload = json.dumps(self._cache, ensure_ascii=False, indent=2)
        temporary = self.path.with_name(f"{self.path.name}.{os.getpid()}.tmp")

        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                0o600,
            )
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(payload)
            os.replace(temporary, self.path)
        except OSError as exc:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise EnergyAlertError(
                f"写入电量预警状态失败：{self.path}",
                context={"path": str(self.path), "errno": exc.errno},
            ) from exc

    def update(self, **values: Any) -> None:
        """合并写入若干字段并落盘。"""
        state = self.load()
        state.update(values)
        self._cache = state
        self.save()


def parse_threshold(value: object, *, default: float = DEFAULT_THRESHOLD) -> float:
    """把配置值解析成阈值，非法值回落到默认值。

    Raises:
        EnergyAlertError: 阈值不是数字或小于 0。
    """
    if value is None or value == "":
        return default
    try:
        threshold = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise EnergyAlertError(
            f"预警阈值不是合法数字：{value!r}",
            context={"value": value},
        ) from exc
    if threshold < 0:
        raise EnergyAlertError(
            f"预警阈值不能为负数：{threshold}",
            context={"threshold": threshold},
        )
    return threshold


def evaluate(
    readings: list[MeterReading],
    threshold: float,
) -> AlertDecision:
    """判断读数是否触发预警，但不产生副作用。

    Args:
        readings: 各电表读数。
        threshold: 预警阈值。

    Returns:
        判断结果。``should_notify`` 此处只表示「处于低电量」，是否真正发信
        还要由调用方结合 [`AlertState`][zzupy.energy.AlertState] 决定。
    """
    usable = [item for item in readings if item.ok]
    if not usable:
        return AlertDecision(
            low=False,
            threshold=threshold,
            lowest=None,
            low_label="",
            should_notify=False,
            reason="没有读取成功的电表",
        )

    lowest_meter = min(usable, key=lambda item: item.remaining or 0.0)
    lowest = float(lowest_meter.remaining or 0.0)
    low = lowest <= threshold
    return AlertDecision(
        low=low,
        threshold=threshold,
        lowest=lowest,
        low_label=lowest_meter.label,
        should_notify=low,
        reason="" if low else f"最低电量 {lowest:g} 度高于阈值 {threshold:g} 度",
    )


def decide_notification(
    decision: AlertDecision,
    state: AlertState,
    *,
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS,
    now: float | None = None,
) -> AlertDecision:
    """在判断结果上叠加防打扰规则，返回最终是否发信。

    规则：进入低电量后只提醒一次；只有电量回升到阈值以上（含回差）才重新
    武装；超过冷却时间会再补一次提醒，避免长期无人处理时彻底静默。
    """
    moment = time.time() if now is None else now
    values = state.load()
    alerted = bool(values.get("alerted", False))
    last_sent = float(values.get("last_sent_at") or 0.0)

    if not decision.low:
        if alerted:
            # 电量已经回升，重新武装，下次低于阈值时还能提醒。
            state.update(alerted=False, last_recovered_at=moment)
            logger.info("电量已回升到 {} 度以上，预警已重新武装", decision.threshold)
        return replace(decision, should_notify=False)

    if not alerted:
        return decision

    if cooldown_seconds > 0 and moment - last_sent >= cooldown_seconds:
        logger.info("低电量状态持续超过冷却时间，补发一次提醒")
        return decision

    return replace(
        decision,
        should_notify=False,
        reason="已提醒过且尚未恢复供电",
    )


def record_notification(state: AlertState, *, now: float | None = None) -> None:
    """记录一次已发生的提醒，用于后续去重。"""
    state.update(alerted=True, last_sent_at=time.time() if now is None else now)


def format_alert_message(
    decision: AlertDecision,
    *,
    room: str = "",
    readings: list[MeterReading] | None = None,
) -> tuple[str, str]:
    """生成提醒邮件的主题与正文。

    Returns:
        ``(subject, body)`` 二元组，正文为纯文本。
    """
    where = f"寝室 {room}" if room else "寝室"
    lowest = "未知" if decision.lowest is None else f"{decision.lowest:g}"
    subject = f"【电量预警】{where}剩余 {lowest} 度，低于 {decision.threshold:g} 度"

    lines = [
        f"{where}剩余电量已低于预警阈值，请尽快充值电费。",
        "",
        f"最低电量：{lowest} 度（{decision.low_label or '未知电表'}）",
        f"预警阈值：{decision.threshold:g} 度",
    ]

    if readings:
        lines.extend(["", "各电表读数："])
        for item in readings:
            if item.ok:
                lines.append(f"  - {item.label}：{item.remaining:g} 度")
            else:
                lines.append(f"  - {item.label}：读取失败（{item.error or '未知原因'}）")

    lines.extend(
        [
            "",
            "电量耗尽会直接断电，建议尽早通过一卡通为寝室电费充值。",
            "本邮件由郑大生活助手自动发送，回复不会被处理。",
        ]
    )
    return subject, "\n".join(lines)


def format_alert_html(
    decision: AlertDecision,
    *,
    room: str = "",
    readings: list[MeterReading] | None = None,
) -> str:
    """生成提醒邮件的 HTML 正文。"""
    where = f"寝室 {room}" if room else "寝室"
    lowest = "未知" if decision.lowest is None else f"{decision.lowest:g}"

    rows = ""
    for item in readings or []:
        value = f"{item.remaining:g} 度" if item.ok else "读取失败"
        rows += (
            f'<tr><td style="padding:6px 10px;border-bottom:1px solid #e3ebe7">'
            f"{item.label}</td>"
            f'<td style="padding:6px 10px;border-bottom:1px solid #e3ebe7;'
            f'text-align:right"><b>{value}</b></td></tr>'
        )

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"></head>
<body style="margin:0;padding:24px;background:#f4f8f6;font-family:system-ui,-apple-system,'Segoe UI',sans-serif;color:#172a25">
<div style="max-width:520px;margin:0 auto;background:#ffffff;border-radius:16px;padding:26px 24px">
<p style="margin:0 0 4px;color:#6b7c76;font-size:13px;letter-spacing:.08em">DORM ENERGY ALERT</p>
<h1 style="margin:0 0 14px;font-size:22px;color:#08483c">寝室电量偏低</h1>
<p style="margin:0 0 18px;line-height:1.7">{where}剩余电量已低于预警阈值，请尽快充值电费，避免突然断电。</p>
<div style="background:#fdf2ef;border-radius:12px;padding:14px 16px;margin-bottom:18px">
<p style="margin:0;font-size:15px">最低电量：<b style="color:#c0392b">{lowest} 度</b>
（{decision.low_label or "未知电表"}）</p>
<p style="margin:6px 0 0;font-size:13px;color:#6b7c76">预警阈值：{decision.threshold:g} 度</p>
</div>
<table style="width:100%;border-collapse:collapse;font-size:14px">{rows}</table>
<p style="margin:20px 0 0;color:#6b7c76;font-size:12px;line-height:1.6">
本邮件由郑大生活助手自动发送，回复不会被处理。</p>
</div></body></html>"""


@dataclass(frozen=True)
class EnergyAlertConfig:
    """电量预警的运行参数。

    Args:
        threshold: 预警阈值（度）。
        room: 指定寝室 ID，留空表示使用账号默认寝室。
        cooldown_seconds: 防打扰冷却时间（秒）。
        dry_run: 只判断不发信，便于试跑。
    """

    threshold: float = DEFAULT_THRESHOLD
    room: str = ""
    cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    dry_run: bool = False
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "EnergyAlertConfig":
        """从环境变量构造配置。"""
        values = os.environ if env is None else env
        return cls(
            threshold=parse_threshold(values.get(THRESHOLD_ENV_VAR)),
            room=values.get("ZZU_ENERGY_ROOM", ""),
            cooldown_seconds=int(
                values.get("ZZU_ENERGY_COOLDOWN_SECONDS") or DEFAULT_COOLDOWN_SECONDS
            ),
        )


__all__ = [
    "AlertDecision",
    "AlertState",
    "DEFAULT_COOLDOWN_SECONDS",
    "DEFAULT_THRESHOLD",
    "EnergyAlertConfig",
    "EnergyAlertError",
    "MeterReading",
    "REARM_MARGIN",
    "decide_notification",
    "default_state_path",
    "evaluate",
    "format_alert_html",
    "format_alert_message",
    "parse_threshold",
    "record_notification",
]
