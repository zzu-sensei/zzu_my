"""学业概览与教务网页端解析的轻量回归检查。"""

from types import SimpleNamespace

from api.index import _best_attempts, _gpa_summary
from zzupy.model.eas import Grade
from zzupy.web import StudentWebEASClient


def grade(
    course: str,
    code: str,
    semester: str,
    gp: float | None,
    credits: float,
    score: str,
) -> Grade:
    return Grade.model_validate(
        {
            "courseName": course,
            "courseCode": code,
            "semester": semester,
            "gp": gp,
            "credits": credits,
            "score": score,
        }
    )


def main() -> None:
    assert StudentWebEASClient.TOKEN_LOGIN_URL.endswith("/cas/t/login")
    assert StudentWebEASClient.STUDENT_SSO_URL.endswith("/student/sso/login")
    values = [
        grade("高等数学", "MATH-1", "2024-2025-1", 2.7, 5, "78"),
        grade("高等数学", "MATH-1", "2024-2025-2", 4.0, 5, "95"),
        grade("大学英语", "ENG-1", "2024-2025-1", 3.7, 2, "88"),
        grade("通识选修", "OPT-1", "2024-2025-1", None, 2, "优秀"),
    ]
    best = _best_attempts(values)
    assert len(best) == 3
    assert next(item for item in best if item.lesson_code == "MATH-1").gp == 4.0

    summary = _gpa_summary(values)
    assert summary["course_count"] == 4
    assert summary["best_attempt_course_count"] == 3
    assert summary["included_course_count"] == 2
    assert summary["credits"] == 7
    assert summary["gpa"] == round((4.0 * 5 + 3.7 * 2) / 7, 4)

    response = SimpleNamespace(
        url="https://jwxt.zzu.edu.cn/student/for-std/grade/sheet/semester-index/123456",
        text="",
    )
    assert StudentWebEASClient._extract_student_id(response) == 123456
    response = SimpleNamespace(url="https://example.invalid", text="var studentId = 654321;")
    assert StudentWebEASClient._extract_student_id(response) == 654321


if __name__ == "__main__":
    main()
