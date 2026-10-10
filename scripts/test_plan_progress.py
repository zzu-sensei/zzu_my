"""培养计划解析与完成度统计的自检。

夹具按**真实页面结构**构造：数据以 JavaScript 对象字面量内联在 ``var model = ...``
里（单引号、裸键、``$type`` 标记），字段名用 ``credits`` / ``subModuleNum`` /
``allCourseList`` / ``resultType``，与教务实际返回一致。

    .venv\\Scripts\\python.exe scripts\\test_plan_progress.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from zzupy.plan import (  # noqa: E402
    PlanParseError,
    course_passed,
    extract_plan_model,
    format_completion,
    match_completion,
    parse_numeric_score,
    parse_plan,
    parse_plan_page,
)
from zzupy.web.jsdata import (  # noqa: E402
    JsLiteralError,
    extract_js_variable,
    parse_js_literal,
    slice_js_array,
    slice_js_object,
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _result(name: str) -> dict:
    return {"$type": "ResultType", "$name": name}


def _summary(
    passed: float = 0.0,
    taking: float = 0.0,
    failed: float = 0.0,
    passed_sub: int = 0,
) -> dict:
    return {
        "passedCredits": passed,
        "takingCredits": taking,
        "failedCredits": failed,
        "passedSubModuleNum": passed_sub,
        "inCredits": 0,
        "logicCredits": 0,
    }


def _course(
    code: str,
    name: str,
    credits: float,
    result: str,
    *,
    compulsory: bool = True,
    term: int = 1,
    score: str = "",
    gp: float | None = None,
) -> dict:
    return {
        "code": code,
        "nameZh": name,
        "nameEn": name,
        "credits": credits,
        "compulsory": compulsory,
        "resultType": _result(result),
        "finalResultType": _result(result),
        "gradeStr": score,
        "gp": gp,
        "terms": [{"$type": "Term", "$name": f"TERM_{term}"}],
    }


def _module(
    module_id: int,
    name: str,
    required_credits: float,
    courses: list[dict],
    summary: dict,
    *,
    children: list[dict] | None = None,
) -> dict:
    return {
        "moduleId": module_id,
        "nameZh": name,
        "nameEn": name,
        "requireInfo": {"credits": required_credits, "subModuleNum": 0},
        "completionSummary": summary,
        "allCourseList": courses,
        "courseList": courses,
        "children": children or [],
    }


#: 精简版真实模型：4 个模块，总要求 175 学分；含在修与未通过。
REAL_MODEL = {
    "id": 123456,
    "requireInfo": {"credits": 175, "subModuleNum": 4},
    "completionSummary": _summary(passed=102.5, taking=24.0, failed=72.5, passed_sub=1),
    "gpa": 3.8381,
    "student": {"nameZh": "某同学", "code": "202400000000"},
    "program": {"nameZh": "2024级电气工程及其自动化人才培养方案"},
    "moduleList": [
        _module(
            112940,
            "必修课",
            147,
            [
                _course("371061", "大学英语（IV）", 2, "PASSED", term=4, score="84", gp=3.2),
                _course("022056", "微机原理与单片机应用", 3, "TAKING", term=4),
                _course("022015", "电磁场", 2, "UNREPAIRED", term=4, score="45", gp=0.0),
            ],
            _summary(passed=83.5, taking=18.0, failed=63.5),
        ),
        _module(112942, "校_任选课", 5, [], _summary(passed=6.0)),
        _module(
            112943,
            "院_任选课",
            12,
            [
                _course("024061", "电气工程导论 （限选)", 1, "PASSED", term=4, score="90"),
                _course("023031", "热力发电厂", 2, "TAKING", compulsory=False, term=7),
            ],
            _summary(passed=7.0, taking=4.0),
        ),
        _module(
            114396,
            "限选课",
            11,
            [
                _course("491003", "体育（III）", 1, "PASSED", term=3, score="85"),
                _course("331002", "国家安全教育", 3, "TAKING", term=1),
            ],
            _summary(passed=7.0, taking=2.0),
        ),
    ],
}


def _as_js_literal(value: object) -> str:
    """把 Python 对象渲染成 JS 对象字面量的近似写法，用于测试解析器。

    用单引号、裸键，模拟教务的真实写法（``json.dumps`` 会产出双引号 JSON，
    那样就测不到 JS 字面量的能力了）。
    """
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            rendered_key = key if key.replace("_", "").isalnum() else f"'{key}'"
            parts.append(f"{rendered_key}:{_as_js_literal(item)}")
        return "{" + ",".join(parts) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_as_js_literal(item) for item in value) + "]"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


# ---------------------------------------------------------------------------
# JS 字面量解析
# ---------------------------------------------------------------------------


def test_parse_js_literal_basics() -> None:
    assert parse_js_literal("{'a':1,'b':'x'}") == {"a": 1, "b": "x"}
    # 裸键、$ 开头的键
    assert parse_js_literal("{credits:147,'$type':'ResultType'}") == {
        "credits": 147,
        "$type": "ResultType",
    }
    # \uXXXX 转义（教务真实写法）
    assert parse_js_literal(r"'\u5FC5\u4FEE\u8BFE'") == "必修课"
    # 转义引号
    assert parse_js_literal(r"'it\'s ok'") == "it's ok"
    # 嵌套与数组
    assert parse_js_literal("{a:[1,2,{b:null,c:true}]}") == {
        "a": [1, 2, {"b": None, "c": True}]
    }
    # 负数、浮点、尾随逗号
    assert parse_js_literal("[-1.5, 2e3, ]") == [-1.5, 2000.0]
    assert parse_js_literal("{a:1,}") == {"a": 1}


def test_parse_js_literal_rejects_non_literals() -> None:
    """不是数据字面量时必须报错，绝不求值。"""
    for bad in (
        "new Date()",
        "someVariable",
        "function(){}",
        "{a: alert(1)}",
        "{a:1",
        "[1,2",
        "",
    ):
        try:
            parse_js_literal(bad)
        except JsLiteralError:
            pass
        else:
            raise AssertionError(f"{bad!r} 应该被拒绝")


def test_slice_helpers() -> None:
    text = "xx {a:'}'} yy"
    start = text.index("{")
    assert slice_js_object(text, start) == "{a:'}'}"  # 字符串里的 } 不干扰配平
    text2 = "[[1,2],'[{',]"
    assert slice_js_array(text2, 0) is not None
    assert slice_js_object(text, 0) is None
    assert slice_js_array("{a:1}", 0) is None


def test_extract_js_variable() -> None:
    html = (
        "<script>var data = {}; var model = "
        + _as_js_literal(REAL_MODEL)
        + ";</script>"
    )
    # 无 require_keys 时可能命中空的那个 var data
    assert extract_js_variable(html, ["data"]) == {}
    got = extract_js_variable(html, ["model"], require_keys=("moduleList",))
    assert got is not None and len(got["moduleList"]) == 4
    # 名字不存在
    assert extract_js_variable(html, ["nope"]) is None


# ---------------------------------------------------------------------------
# 计划解析
# ---------------------------------------------------------------------------


def test_parse_plan_modules_and_summary() -> None:
    plan = parse_plan(REAL_MODEL)
    assert plan.id == 123456
    assert plan.required_credits == 175.0
    assert plan.required_sub_modules == 4
    assert plan.passed_credits == 102.5
    assert plan.taking_credits == 24.0
    assert plan.failed_credits == 72.5

    assert [m.name for m in plan.modules] == [
        "必修课",
        "校_任选课",
        "院_任选课",
        "限选课",
    ]
    assert plan.module_credits == 175.0
    assert plan.module_credits == plan.required_credits

    by_name = {m.name: m for m in plan.modules}
    assert by_name["必修课"].required_credits == 147.0
    assert by_name["必修课"].passed_credits == 83.5
    assert by_name["必修课"].taking_credits == 18.0
    assert by_name["必修课"].missing == 63.5
    assert by_name["必修课"].done is False
    assert by_name["校_任选课"].done is True  # 6 >= 5
    # 要求 0 学分且无课时的模块不应出现
    assert all(m.required_credits > 0 for m in plan.modules)


def test_parse_plan_course_fields() -> None:
    plan = parse_plan(REAL_MODEL)
    module = next(m for m in plan.modules if m.name == "必修课")
    course = next(c for c in module.courses if c.code == "371061")
    assert course.name == "大学英语（IV）"
    assert course.credits == 2.0
    assert course.compulsory is True
    assert course.terms == (4,)
    assert course.result == "PASSED"
    assert course.passed is True
    assert course.score == "84"
    assert course.gp == 3.2

    taking = next(c for c in module.courses if c.code == "022056")
    assert taking.taking is True
    assert taking.passed is False

    failed = next(c for c in module.courses if c.code == "022015")
    assert failed.passed is False
    assert failed.taking is False


def test_empty_module_gets_note() -> None:
    model = json.loads(json.dumps(REAL_MODEL))
    # 改成「要求 12 学分但一节课都不列」
    model["moduleList"][1]["requireInfo"]["credits"] = 12
    plan = parse_plan(model)
    module = next(m for m in plan.modules if m.name == "校_任选课")
    assert module.required_credits == 12.0
    assert "未列出课程" in module.note


def test_nested_child_modules_are_kept() -> None:
    """父模块与子模块都是独立学分桶，都不能丢。"""
    child = _module(
        116340, "实践教学", 25,
        [_course("025032", "毕业设计", 16, "TAKING", term=8)],
        _summary(taking=16.0),
    )
    model = json.loads(json.dumps(REAL_MODEL))
    model["moduleList"][0]["children"] = [child]
    plan = parse_plan(model)
    names = [m.name for m in plan.modules]
    assert "必修课" in names and "实践教学" in names
    assert names.index("必修课") < names.index("实践教学")


def test_parse_plan_rejects_bad_shapes() -> None:
    for bad in ([], "不是对象", 42, None, {"id": 1}, {"requireInfo": {}}):
        try:
            parse_plan(bad)
        except PlanParseError:
            pass
        else:
            raise AssertionError(f"{bad!r} 应该被拒绝")


def test_parse_plan_page_from_html() -> None:
    html = (
        "<html><script>var model = "
        + _as_js_literal(REAL_MODEL)
        + ";</script></html>"
    )
    assert extract_plan_model(html) is not None
    plan = parse_plan_page(html)
    assert plan.required_credits == 175.0
    assert len(plan.modules) == 4

    # 页面里没有 model 时要报错
    for bad in ("<html>空</html>", "<script>var model = {};</script>"):
        try:
            parse_plan_page(bad)
        except PlanParseError:
            pass
        else:
            raise AssertionError("应该报错")


def test_fallback_when_page_lacks_summary() -> None:
    """页面没给汇总时，退回按成绩自行统计。"""
    model = json.loads(json.dumps(REAL_MODEL))
    model["completionSummary"] = {}
    for module in model["moduleList"]:
        module["completionSummary"] = {}
    plan = parse_plan(model)
    assert plan.passed_credits == 0.0
    # 没有汇总时 effective 仍为 0（fallback 未设置），不会虚报
    assert plan.effective_passed_credits == 0.0


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def test_format_completion() -> None:
    plan = parse_plan(REAL_MODEL)
    report = format_completion(plan)
    assert "培养计划完成度：102.5 / 175 学分" in report
    assert "还差 72.5 学分" in report
    assert "在修 24" in report
    assert "必修课" in report
    assert "已达标" in report
    assert "（在修 18）" in report


def test_training_plan_to_dict() -> None:
    plan = parse_plan(REAL_MODEL)
    data = plan.to_dict()
    assert data["id"] == 123456
    assert data["required_credits"] == 175.0
    assert data["passed_credits"] == 102.5
    assert data["missing"] == 72.5
    assert len(data["modules"]) == 4
    assert data["modules"][0]["courses"][0]["code"]


# ---------------------------------------------------------------------------
# 通过判定与成绩对照（页面无结课结果时的回退口径）
# ---------------------------------------------------------------------------


def test_parse_numeric_score() -> None:
    assert parse_numeric_score("92") == 92.0
    assert parse_numeric_score(85) == 85.0
    assert parse_numeric_score("优秀") is None
    assert parse_numeric_score(None) is None


def test_course_passed_rules() -> None:
    assert course_passed({"passed": True, "score": "30"}) is True
    assert course_passed({"passed": False, "score": "95"}) is False
    assert course_passed({"score": "60"}) is True
    assert course_passed({"score": "59"}) is False
    assert course_passed({"score": "优秀", "gp": 4.0}) is True
    assert course_passed({"score": "不及格", "gp": 0.0}) is False
    assert course_passed({}) is False
    assert course_passed({"passed": "是"}) is True
    assert course_passed({"passed": "否"}) is False


def test_match_completion_by_code_and_name() -> None:
    plan = parse_plan(REAL_MODEL)
    grades = [
        {"course": "大学英语（IV）", "credits": 2, "code": "371061", "score": "84"},
        # 没有编号，只能按课程名匹配
        {"course": "电磁场", "credits": 2, "score": "45"},
        # 完全不在计划里
        {"course": "某门计划外的课", "credits": 3, "code": "999999", "score": "90"},
    ]
    completion = match_completion(plan, grades)
    assert completion.earned_credits == 2.0
    assert len(completion.outside_plan) == 1
    assert completion.outside_plan[0].name == "某门计划外的课"
    assert completion.outside_plan_credits == 3.0
    assert len(completion.failed) == 1
    assert completion.failed[0].name == "电磁场"


def test_match_completion_retake_counted_once() -> None:
    plan = parse_plan(REAL_MODEL)
    grades = [
        {"course": "电磁场", "credits": 2, "code": "022015", "score": "45", "passed": False},
        {"course": "电磁场", "credits": 2, "code": "022015", "score": "78", "passed": True},
    ]
    completion = match_completion(plan, grades)
    assert completion.earned_credits == 2.0
    assert completion.failed == ()


def test_failed_and_taking_course_lists() -> None:
    """未通过/在修课程清单要从真实的结课结果里筛出来。

    真实的未通过取值是 ``UNREPAIRED``（挂科未重修），不是 ``FAILED``；只匹配
    ``FAILED`` 会一门都列不出来。
    """
    plan = parse_plan(REAL_MODEL)
    failed = plan.failed_courses
    assert [c.code for c in failed] == ["022015"], [c.name for c in failed]
    assert failed[0].name == "电磁场"
    assert failed[0].credits == 2.0

    taking = plan.taking_courses
    codes = sorted(c.code for c in taking)
    assert codes == ["022056", "023031", "331002"], codes

    report = format_completion(plan)
    assert "未通过 1 门" in report
    assert "在修 3 门" in report
    assert "口径不同" in report  # 两个口径的差异要有说明


def test_course_result_classification() -> None:
    """三种结课结果都要能正确归类。"""
    from zzupy.plan import PlannedCourse

    plan = parse_plan(REAL_MODEL)
    courses = {c.code: c for m in plan.modules for c in m.courses}
    assert courses["371061"].passed is True
    assert courses["022015"].failed is True
    assert courses["022015"].passed is False
    assert courses["022056"].taking is True
    # 兼容大小写与常见变体
    assert PlannedCourse(result="UNREPAIRED").failed is True
    assert PlannedCourse(result="unrepaired").failed is True
    assert PlannedCourse(result="FAILED").failed is True
    assert PlannedCourse(result="PASSED").failed is False
    assert PlannedCourse(result="").failed is False


def main() -> None:
    test_parse_js_literal_basics()
    test_parse_js_literal_rejects_non_literals()
    test_slice_helpers()
    test_extract_js_variable()
    test_parse_plan_modules_and_summary()
    test_parse_plan_course_fields()
    test_empty_module_gets_note()
    test_nested_child_modules_are_kept()
    test_parse_plan_rejects_bad_shapes()
    test_parse_plan_page_from_html()
    test_fallback_when_page_lacks_summary()
    test_format_completion()
    test_training_plan_to_dict()
    test_parse_numeric_score()
    test_course_passed_rules()
    test_match_completion_by_code_and_name()
    test_match_completion_retake_counted_once()
    test_failed_and_taking_course_lists()
    test_course_result_classification()
    print("培养计划解析与完成度自检全部通过。")


if __name__ == "__main__":
    main()
