"""寝室耗电速度估算。

每次读到电量时把读数按时间记下来，之后用最小二乘拟合出耗电速度，进而估算
「还能用多久」。这样做比单看两次读数的差值稳得多：抄表噪声、四舍五入、以及
中途充值造成的跳变都会被摊平。

数据保存在一个 JSON Lines 文件里，追加写入、定期裁剪，不需要数据库。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Iterable, Mapping

from zzupy.logging import logger

#: 默认的历史文件位置。与电量预警状态放在同一个目录下。
HISTORY_ENV_VAR: Final = "ZZU_ENERGY_HISTORY"

#: 只保留最近这么多天的数据。太久以前的数据对估算当天速度没有意义。
DEFAULT_RETENTION_DAYS: Final = 30

#: 估算耗电速度时最多回看这么多天。
DEFAULT_WINDOW_DAYS: Final = 7

#: 少于这么多小时的数据不足以估算，直接放弃。
MIN_WINDOW_HOURS: Final = 6.0

#: 拟合出的速度小于该值（度/天）时视为「几乎不耗电」，不给天数估计。
NEGLIGIBLE_RATE: Final = 0.01

_HISTORY_FILE_NAME: Final = "energy_history.jsonl"
_APP_DIR_NAME: Final = "ZZU.Py"


class EnergyHistoryError(Exception):
    """耗电历史读写失败。"""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.context = dict(context or {})

    def __str__(self) -> str:
        return self.message


@dataclass(frozen=True)
class MeterHistoryEntry:
    """某个电表在某一时刻的读数。

    Args:
        timestamp: Unix 时间戳（秒）。
        meter_id: 完整电表 ID。
        label: 电表名称。
        remaining: 剩余电量（度）。
    """

    timestamp: float
    meter_id: str
    label: str
    remaining: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": round(self.timestamp, 3),
            "id": self.meter_id,
            "label": self.label,
            "q": self.remaining,
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "MeterHistoryEntry | None":
        """从 JSON 对象还原；字段缺失时返回 ``None`` 而不是抛错。"""
        try:
            return cls(
                timestamp=float(raw["t"]),
                meter_id=str(raw.get("id") or ""),
                label=str(raw.get("label") or "寝室电表"),
                remaining=float(raw["q"]),
            )
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class DrainEstimate:
    """某个电表的耗电速度估算结果。

    Args:
        label: 电表名称。
        meter_id: 完整电表 ID。
        latest: 最近一次读数。
        rate_per_day: 拟合出的日均耗电量（度/天）。
        days_left: 按当前速度还能用多少天；无法估算时为 ``None``。
        samples: 参与拟合的读数个数。
        window_hours: 参与拟合的时间跨度（小时）。
        note: 数据不足或异常时的说明。
    """

    label: str
    meter_id: str
    latest: float
    rate_per_day: float
    days_left: float | None
    samples: int
    window_hours: float
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "meter_id": self.meter_id,
            "latest": self.latest,
            "rate_per_day": round(self.rate_per_day, 4),
            "days_left": None if self.days_left is None else round(self.days_left, 2),
            "samples": self.samples,
            "window_hours": round(self.window_hours, 2),
            "note": self.note,
        }


def default_history_path() -> Path:
    """返回默认的历史文件路径。"""
    if override := os.environ.get(HISTORY_ENV_VAR):
        return Path(override).expanduser()

    if appdata := os.environ.get("APPDATA"):
        return Path(appdata) / _APP_DIR_NAME / _HISTORY_FILE_NAME

    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    return base / "zzupy" / _HISTORY_FILE_NAME


class EnergyHistory:
    """按时间记录电表读数，并提供耗电速度估算。

    Args:
        path: 历史文件路径；为 ``None`` 时使用默认位置。
        retention_days: 保留天数。
    """

    def __init__(
        self,
        path: Path | None = None,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self.path = path if path is not None else default_history_path()
        self.retention_days = retention_days

    def load(self) -> list[MeterHistoryEntry]:
        """读取全部有效记录；文件不存在或某行损坏都会跳过而不是报错。"""
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return []
        except OSError as exc:
            logger.warning("读取耗电历史失败：{}", exc)
            return []

        entries: list[MeterHistoryEntry] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                # 只跳过坏行，不影响其它记录。
                continue
            if not isinstance(parsed, dict):
                continue
            entry = MeterHistoryEntry.from_dict(parsed)
            if entry is not None:
                entries.append(entry)
        entries.sort(key=lambda item: item.timestamp)
        return entries

    def record(self, readings: Iterable[Any], *, now: float | None = None) -> int:
        """追加一批读数，返回写入条数。

        Args:
            readings: 可迭代对象，每项需有 ``meter_id``、``label``、``remaining``
                属性；``remaining`` 为 ``None`` 的条目会被跳过。
            now: 统一使用的时间戳，便于测试注入。
        """
        moment = time.time() if now is None else now
        lines: list[str] = []
        for item in readings:
            remaining = getattr(item, "remaining", None)
            if remaining is None:
                continue
            entry = MeterHistoryEntry(
                timestamp=moment,
                meter_id=str(getattr(item, "meter_id", "") or ""),
                label=str(getattr(item, "label", "") or "寝室电表"),
                remaining=float(remaining),
            )
            lines.append(json.dumps(entry.to_dict(), ensure_ascii=False))

        if not lines:
            return 0

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write("\n".join(lines) + "\n")
        except OSError as exc:
            raise EnergyHistoryError(
                f"写入耗电历史失败：{self.path}",
                context={"path": str(self.path), "errno": exc.errno},
            ) from exc

        self._prune_if_needed(moment)
        return len(lines)

    def _prune_if_needed(self, moment: float) -> None:
        """只在确实存在过期数据时才重写文件。"""
        cutoff = moment - self.retention_days * 86400
        entries = self.load()
        kept = [item for item in entries if item.timestamp >= cutoff]
        if len(kept) == len(entries):
            return
        try:
            payload = "\n".join(
                json.dumps(item.to_dict(), ensure_ascii=False) for item in kept
            )
            self.path.write_text(
                payload + ("\n" if payload else ""),
                encoding="utf-8",
            )
            logger.debug("耗电历史已裁剪：{} -> {} 条", len(entries), len(kept))
        except OSError as exc:
            logger.warning("裁剪耗电历史失败：{}", exc)

    def estimate(
        self,
        *,
        window_days: int = DEFAULT_WINDOW_DAYS,
        now: float | None = None,
    ) -> list[DrainEstimate]:
        """估算各电表的耗电速度。

        估算只使用已经落盘的记录。请在调用前先用
        [`record()`][zzupy.energy_history.EnergyHistory.record] 写入最新读数，
        这样「查一次电量」就同时完成了采样。

        Args:
            window_days: 回看天数。
            now: 参考时刻，用于确定窗口起点。

        Returns:
            按电表分组的结果；数据不足的电表 ``note`` 会说明原因。
        """
        moment = time.time() if now is None else now
        cutoff = moment - window_days * 86400
        entries = [item for item in self.load() if item.timestamp >= cutoff]

        grouped: dict[str, list[MeterHistoryEntry]] = {}
        for entry in entries:
            grouped.setdefault(entry.meter_id, []).append(entry)

        estimates: list[DrainEstimate] = []
        for meter_id, samples in grouped.items():
            estimates.append(_estimate_one(meter_id, samples))
        return estimates


def _estimate_one(
    meter_id: str,
    samples: list[MeterHistoryEntry],
) -> DrainEstimate:
    """对单个电表做最小二乘拟合。"""
    label = samples[-1].label if samples else "寝室电表"
    latest = samples[-1].remaining if samples else 0.0

    if len(samples) < 2:
        return DrainEstimate(
            label=label,
            meter_id=meter_id,
            latest=latest,
            rate_per_day=0.0,
            days_left=None,
            samples=len(samples),
            window_hours=0.0,
            note="只有一个采样点，多查几次即可估算",
        )

    first, last = samples[0], samples[-1]
    window_hours = (last.timestamp - first.timestamp) / 3600.0
    if window_hours < MIN_WINDOW_HOURS:
        return DrainEstimate(
            label=label,
            meter_id=meter_id,
            latest=latest,
            rate_per_day=0.0,
            days_left=None,
            samples=len(samples),
            window_hours=window_hours,
            note=f"时间跨度不足 {MIN_WINDOW_HOURS:g} 小时，继续采样中",
        )

    # 以最早一次采样为原点，避免大时间戳带来的数值误差。
    origin = first.timestamp
    xs = [(item.timestamp - origin) / 86400.0 for item in samples]
    ys = [item.remaining for item in samples]
    count = len(samples)
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    denominator = sum((x - mean_x) ** 2 for x in xs)
    if denominator <= 0:
        return DrainEstimate(
            label=label,
            meter_id=meter_id,
            latest=latest,
            rate_per_day=0.0,
            days_left=None,
            samples=count,
            window_hours=window_hours,
            note="采样时间重合，无法拟合",
        )

    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denominator
    rate = -slope

    if abs(rate) < NEGLIGIBLE_RATE:
        # 几乎持平：既可能是真的不耗电，也可能是采样太短，总之不给天数估计。
        return DrainEstimate(
            label=label,
            meter_id=meter_id,
            latest=latest,
            rate_per_day=abs(rate),
            days_left=None,
            samples=count,
            window_hours=window_hours,
            note="几乎没有耗电",
        )

    if rate < 0:
        # 电量为上升趋势：说明期间充过值（或仪表回绕），此时不能按耗电估算。
        return DrainEstimate(
            label=label,
            meter_id=meter_id,
            latest=latest,
            rate_per_day=0.0,
            days_left=None,
            samples=count,
            window_hours=window_hours,
            note="期间电量没有下降（可能刚充值），暂不估算",
        )

    return DrainEstimate(
        label=label,
        meter_id=meter_id,
        latest=latest,
        rate_per_day=rate,
        days_left=latest / rate if latest > 0 else 0.0,
        samples=count,
        window_hours=window_hours,
    )


def format_drain_line(estimate: DrainEstimate) -> str:
    """把估算结果格式化成一行中文说明。"""
    if estimate.days_left is None:
        detail = f"（{estimate.note}）" if estimate.note else ""
        return f"{estimate.label}：{estimate.latest:g} 度，暂无法估算耗电速度{detail}"
    return (
        f"{estimate.label}：{estimate.latest:g} 度，"
        f"日均 {estimate.rate_per_day:.2f} 度，"
        f"约还能用 {format_days(estimate.days_left)}"
    )


def format_days(days: float) -> str:
    """把天数格式化成人能读的形式。"""
    if days < 1:
        hours = days * 24
        if hours < 1:
            return f"{hours * 60:.0f} 分钟"
        return f"{hours:.1f} 小时"
    if days < 10:
        return f"{days:.1f} 天"
    return f"{days:.0f} 天"


__all__ = [
    "DEFAULT_RETENTION_DAYS",
    "DEFAULT_WINDOW_DAYS",
    "DrainEstimate",
    "EnergyHistory",
    "EnergyHistoryError",
    "HISTORY_ENV_VAR",
    "MeterHistoryEntry",
    "MIN_WINDOW_HOURS",
    "default_history_path",
    "format_days",
    "format_drain_line",
]
