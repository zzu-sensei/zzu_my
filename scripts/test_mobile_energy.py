from __future__ import annotations

import sys
from pathlib import Path


PYTHON_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "flutter-app"
    / "android"
    / "app"
    / "src"
    / "main"
    / "python"
)
sys.path.insert(0, str(PYTHON_SOURCE))

from mobile_zzupy import discover_meter_energy  # noqa: E402


class FakeECard:
    def get_room_dict(self, room_id: str) -> dict[str, str]:
        return {
            "7-2--186": {"8511": "松园 511 寝室"},
            "7-2": {"186": "默认房间", "205": "空调电表"},
            "7-2--205": {"900": "松园 511 空调"},
        }[room_id]

    def get_remaining_energy(self, room_id: str) -> float:
        return {
            "7-2--186-8511": 18.5,
            "7-2--205-900": 9.25,
        }[room_id]


def main() -> None:
    client = FakeECard()
    meters = discover_meter_energy(client, "7-2--186-8511")
    assert [meter["meter_id"] for meter in meters] == [
        "7-2--186-8511",
        "7-2--205-900",
    ]
    assert [meter["label"] for meter in meters] == ["寝室电表", "空调电表"]


if __name__ == "__main__":
    main()
