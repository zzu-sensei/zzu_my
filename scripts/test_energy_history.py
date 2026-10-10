"""耗电速度估算的自检。

    .venv\\Scripts\\python.exe scripts\\test_energy_history.py
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from zzupy.energy_history import (  # noqa: E402
    DrainEstimate,
    EnergyHistory,
    EnergyHistoryError,
    format_days,
    format_drain_line,
)


@dataclass
class Reading:
    """与 MeterReading 结构一致的最小读数对象。"""

    label: str
    meter_id: str
    remaining: float | None = None
    error: str | None = None


HOUR = 3600.0
DAY = 86400.0


def test_no_data(tmp: Path) -> None:
    history = EnergyHistory(tmp / "empty.jsonl")
    assert history.load() == []
    assert history.estimate(now=1000.0) == []


def test_single_sample_cannot_estimate(tmp: Path) -> None:
    history = EnergyHistory(tmp / "single.jsonl")
    history.record([Reading("空调", "b", 10.0)], now=0.0)
    estimates = history.estimate(now=0.0)
    assert len(estimates) == 1
    assert estimates[0].days_left is None
    assert "只有一个采样点" in estimates[0].note
    assert "暂无法估算" in format_drain_line(estimates[0])


def test_short_window_refuses_to_estimate(tmp: Path) -> None:
    history = EnergyHistory(tmp / "short.jsonl")
    # 跨度 2 小时，低于 6 小时下限。
    for hours in (0, 1, 2):
        history.record([Reading("空调", "b", 10.0 - hours)], now=hours * HOUR)
    estimate = history.estimate(now=2 * HOUR)[0]
    assert estimate.days_left is None
    assert "时间跨度不足" in estimate.note


def test_linear_drain_estimate(tmp: Path) -> None:
    """每天正好耗 2 度，应拟合出 2.0 度/天。"""
    history = EnergyHistory(tmp / "linear.jsonl")
    for day in range(4):
        history.record(
            [Reading("空调", "b", 20.0 - 2.0 * day)], now=day * DAY
        )
    estimate = history.estimate(now=3 * DAY)[0]
    assert estimate.samples == 4
    assert abs(estimate.rate_per_day - 2.0) < 1e-6, estimate.rate_per_day
    # 最新读数是 14 度，14 / 2 = 7 天
    assert abs((estimate.days_left or 0) - 7.0) < 1e-6, estimate.days_left
    assert estimate.window_hours == 72.0

    line = format_drain_line(estimate)
    assert "日均 2.00 度" in line, line
    assert "7.0 天" in line, line


def test_noisy_readings_still_reasonable(tmp: Path) -> None:
    """抄表抖动不应该让速度估算跑偏太多。"""
    history = EnergyHistory(tmp / "noisy.jsonl")
    samples = [(0, 20.0), (1, 18.1), (2, 15.9), (3, 14.2), (4, 11.8)]
    for day, quantity in samples:
        history.record([Reading("照明", "a", quantity)], now=day * DAY)
    estimate = history.estimate(now=4 * DAY)[0]
    assert 1.8 < estimate.rate_per_day < 2.2, estimate.rate_per_day


def test_recharge_is_not_treated_as_negative_drain(tmp: Path) -> None:
    """中途充值会让斜率为正，此时应明确说明而不是给出负耗电。"""
    history = EnergyHistory(tmp / "recharge.jsonl")
    for day, quantity in [(0, 5.0), (1, 3.0), (2, 30.0), (3, 29.0)]:
        history.record([Reading("空调", "b", quantity)], now=day * DAY)
    estimate = history.estimate(now=3 * DAY)[0]
    assert estimate.days_left is None
    assert estimate.rate_per_day == 0.0
    assert "没有下降" in estimate.note


def test_flat_reading_is_negligible(tmp: Path) -> None:
    history = EnergyHistory(tmp / "flat.jsonl")
    for day in range(4):
        history.record([Reading("空调", "b", 20.0)], now=day * DAY)
    estimate = history.estimate(now=3 * DAY)[0]
    assert estimate.days_left is None
    assert "几乎没有耗电" in estimate.note


def test_multiple_meters_are_separate(tmp: Path) -> None:
    history = EnergyHistory(tmp / "multi.jsonl")
    for day in range(4):
        history.record(
            [
                Reading("照明", "a", 30.0 - 1.0 * day),
                Reading("空调", "b", 20.0 - 3.0 * day),
            ],
            now=day * DAY,
        )
    estimates = {item.meter_id: item for item in history.estimate(now=3 * DAY)}
    assert set(estimates) == {"a", "b"}
    assert abs(estimates["a"].rate_per_day - 1.0) < 1e-6
    assert abs(estimates["b"].rate_per_day - 3.0) < 1e-6


def test_failed_readings_are_skipped(tmp: Path) -> None:
    history = EnergyHistory(tmp / "skip.jsonl")
    written = history.record(
        [
            Reading("照明", "a", None, error="接口超时"),
            Reading("空调", "b", 5.0),
        ],
        now=0.0,
    )
    assert written == 1
    assert len(history.load()) == 1
    assert history.load()[0].meter_id == "b"


def test_latest_reading_drives_estimate(tmp: Path) -> None:
    history = EnergyHistory(tmp / "latest.jsonl")
    # 每天耗 2 度：20 -> 18 -> 16 -> 14，再查一次得到 12 度。
    for day in range(4):
        history.record([Reading("空调", "b", 20.0 - 2.0 * day)], now=day * DAY)
    history.record([Reading("空调", "b", 12.0)], now=4 * DAY)
    estimate = history.estimate(now=4 * DAY)[0]
    assert estimate.latest == 12.0
    assert estimate.samples == 5
    assert abs(estimate.rate_per_day - 2.0) < 1e-6, estimate.rate_per_day
    assert abs((estimate.days_left or 0) - 6.0) < 1e-6, estimate.days_left


def test_window_excludes_old_data(tmp: Path) -> None:
    history = EnergyHistory(tmp / "window.jsonl")
    # 30 天前的一条旧数据不应该进入 7 天窗口的拟合。
    history.record([Reading("空调", "b", 100.0)], now=0.0)
    for day in range(1, 4):
        history.record([Reading("空调", "b", 20.0 - day)], now=(29 + day) * DAY)
    estimate = history.estimate(window_days=7, now=32 * DAY)[0]
    assert estimate.samples == 3
    assert all(
        entry.remaining <= 20.0 for entry in history.load() if entry.timestamp > 0
    )
    assert abs(estimate.rate_per_day - 1.0) < 1e-6


def test_retention_prunes_old_entries(tmp: Path) -> None:
    history = EnergyHistory(tmp / "prune.jsonl", retention_days=5)
    history.record([Reading("空调", "b", 50.0)], now=0.0)
    history.record([Reading("空调", "b", 40.0)], now=10 * DAY)
    remaining = history.load()
    assert len(remaining) == 1, [item.to_dict() for item in remaining]
    assert remaining[0].remaining == 40.0


def test_corrupt_lines_are_skipped(tmp: Path) -> None:
    path = tmp / "corrupt.jsonl"
    path.write_text(
        '{"t": 0, "id": "a", "label": "照明", "q": 10.0}\n'
        "这不是 JSON\n"
        '{"t": 3600, "id": "a"}\n'
        "\n"
        '{"t": 7200, "id": "a", "label": "照明", "q": 8.0}\n',
        encoding="utf-8",
    )
    entries = EnergyHistory(path).load()
    assert len(entries) == 2, entries
    assert entries[0].remaining == 10.0
    assert entries[1].remaining == 8.0


def test_format_days() -> None:
    assert format_days(0.02) == "29 分钟"
    assert format_days(0.5) == "12.0 小时"
    assert format_days(3.5) == "3.5 天"
    assert format_days(40.0) == "40 天"


def test_write_failure_raises(tmp: Path) -> None:
    # 用一个不可能创建成功的路径（把文件当目录用）。
    blocker = tmp / "blocker"
    blocker.write_text("x", encoding="utf-8")
    history = EnergyHistory(blocker / "nested" / "history.jsonl")
    try:
        history.record([Reading("空调", "b", 1.0)], now=0.0)
    except (EnergyHistoryError, OSError):
        pass
    else:
        raise AssertionError("不可写路径应该报错")


def main() -> None:
    scratch = Path(tempfile.mkdtemp(prefix="zzu-energy-history-"))
    try:
        test_no_data(scratch)
        test_single_sample_cannot_estimate(scratch)
        test_short_window_refuses_to_estimate(scratch)
        test_linear_drain_estimate(scratch)
        test_noisy_readings_still_reasonable(scratch)
        test_recharge_is_not_treated_as_negative_drain(scratch)
        test_flat_reading_is_negligible(scratch)
        test_multiple_meters_are_separate(scratch)
        test_failed_readings_are_skipped(scratch)
        test_latest_reading_drives_estimate(scratch)
        test_window_excludes_old_data(scratch)
        test_retention_prunes_old_entries(scratch)
        test_corrupt_lines_are_skipped(scratch)
        test_format_days()
        test_write_failure_raises(scratch)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    print("耗电速度估算自检全部通过。")


if __name__ == "__main__":
    main()
