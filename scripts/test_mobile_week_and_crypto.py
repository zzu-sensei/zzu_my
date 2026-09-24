from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


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

import gmalg  # noqa: E402
from mobile_zzupy import (  # noqa: E402
    MobileEASClient,
    MobileECardClient,
    MobileWebEASClient,
)
from mobile_bridge import (  # noqa: E402
    _format_clock_time,
    _grade_component_items,
    _grade_components,
    _is_experiment_schedule,
)


class _ScheduleResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "result": 0,
            "data": [
                {
                    "course": {"nameZh": "API 测试课程"},
                    "schedules": [
                        {"weekIndexes": [2, 3], "weekday": 2},
                        {"date": "2026-09-23", "weekday": 3},
                    ],
                    "experimentSchedules": [
                        {
                            "date": "2026-09-24",
                            "weekIndex": 0,
                            "weekday": 4,
                            "startUnit": 7,
                            "lessonType": "EXPERIMENT",
                        }
                    ],
                }
            ],
        }


class _ScheduleClient:
    def get(self, *args, **kwargs) -> _ScheduleResponse:
        return _ScheduleResponse()


class _WebResponse:
    status_code = 200
    headers: dict[str, str] = {}
    content = b""

    def __init__(self, url: str, text: str = "") -> None:
        self.url = url
        self.text = text

    def raise_for_status(self) -> None:
        return None


class _WebClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict | None, dict | None]] = []

    def get(self, url: str, *, headers=None, params=None, follow_redirects=True):
        self.calls.append((url, params, headers))
        if len(self.calls) == 1:
            return _WebResponse("https://jwxt.zzu.edu.cn/student/home")
        return _WebResponse(
            "https://jwxt.zzu.edu.cn/student/for-std/grade/sheet/semester-index/453672"
        )

    def close(self) -> None:
        return None


def main() -> None:
    web = MobileWebEASClient(SimpleNamespace(user_token="test-token"))
    web.client = _WebClient()
    web.login()
    assert web.student_id == 453672
    assert web.client.calls[0] == (
        "https://cas.s.zzu.edu.cn/cas/t/login",
        {"service": "https://jwxt.zzu.edu.cn/student/sso/login"},
        {
            "User-Agent": MobileWebEASClient.USER_AGENT,
            "Authorization": "test-token",
            "X-Id-Token": "test-token",
        },
    )

    eas = object.__new__(MobileEASClient)
    eas.current_semester = {
        "id": 20261,
        "startDate": "2026-09-07",
        "weekIndices": list(range(1, 21)),
    }
    eas.token = "test-token"
    assert eas.resolve_current_week("2026-09-23") == 3
    eas.client = _ScheduleClient()
    assert len(eas.get_teaching_week(3, None)) == 3
    assert _grade_components('平时成绩：88，卷面成绩：92') == {
        "usual_score": "88",
        "paper_score": "92",
    }
    assert _format_clock_time(800) == "08:00"
    assert _format_clock_time("940") == "09:40"
    assert _is_experiment_schedule({"lessonType": "EXPERIMENT"})
    assert _is_experiment_schedule({"lessonType": "实验课"})
    assert not _is_experiment_schedule({"lessonType": "THEORY"})
    assert not _is_experiment_schedule({"lessonType": "PRACTICE"})
    assert _grade_component_items(
        {
            "gradeDetail": [
                {"name": "课堂表现", "score": 95},
                {"name": "课程设计", "score": 88},
            ],
            "finalGrade": 91,
        }
    ) == [
        {"label": "课堂表现", "value": "95"},
        {"label": "课程设计", "value": "88"},
        {"label": "最终成绩", "value": "91"},
    ]

    key = MobileECardClient.SM4_KEY
    plaintext = b"04a1b2c3d4"
    padding = 16 - len(plaintext) % 16
    padded = plaintext + bytes([padding]) * padding
    cipher = gmalg.SM4(key)
    encrypted = b"".join(
        cipher.encrypt(padded[index : index + 16])
        for index in range(0, len(padded), 16)
    )
    assert MobileECardClient._sm4_decrypt(encrypted, key) == plaintext.decode()

    ecard = object.__new__(MobileECardClient)
    try:
        ecard.recharge_energy("", 10, "1-2--41-100")
    except RuntimeError as error:
        assert "支付密码" in str(error)
    else:
        raise AssertionError("An empty payment password must be rejected locally")


if __name__ == "__main__":
    main()
