"""手机端培养计划解析器的自检（与桌面端交叉比对）。

手机端用的是自包含实现 ``mobile_plan_page.py``（不依赖 loguru），桌面端是
``zzupy.plan`` + ``zzupy.web.jsdata``。两者解析同一份真实结构的页面时必须给出
**完全一致**的结果，否则两端会显示不同的完成度。

    .venv\\Scripts\\python.exe scripts\\test_mobile_plan_page.py
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON_SOURCE = (
    REPO_ROOT / "flutter-app" / "android" / "app" / "src" / "main" / "python"
)
sys.path.insert(0, str(PYTHON_SOURCE))
sys.path.insert(0, str(REPO_ROOT))

import mobile_plan_page as mobile  # noqa: E402
from zzupy.plan import parse_plan as desktop_parse_plan  # noqa: E402
from zzupy.plan import parse_plan_page as desktop_parse_page  # noqa: E402
from zzupy.web.jsdata import (  # noqa: E402
    JsLiteralError as DesktopJsError,
    parse_js_literal as desktop_js,
)


# ---------------------------------------------------------------------------
# 夹具：按真实页面结构构造（JS 写法：单引号、裸键、$ 键、\uXXXX）
# ---------------------------------------------------------------------------


def _as_js(value: object) -> str:
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            rendered = key if key.replace("_", "").isalnum() else f"'{key}'"
            parts.append(f"{rendered}:{_as_js(item)}")
        return "{" + ",".join(parts) + "}"
    if isinstance(value, list):
        return "[" + ",".join(_as_js(item) for item in value) + "]"
    if isinstance(value, str):
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _course(code, name, credits, result, *, compulsory=True, term=1, score="", gp=None):
    return {
        "code": code,
        "nameZh": name,
        "credits": credits,
        "compulsory": compulsory,
        "resultType": {"$type": "ResultType", "$name": result},
        "finalResultType": {"$type": "ResultType", "$name": result},
        "gradeStr": score,
        "gp": gp,
        "terms": [{"$type": "Term", "$name": f"TERM_{term}"}],
    }


def _module(module_id, name, required, courses, summary, children=None):
    return {
        "moduleId": module_id,
        "nameZh": name,
        "requireInfo": {"credits": required, "subModuleNum": 0},
        "completionSummary": summary,
        "allCourseList": courses,
        "courseList": courses,
        "children": children or [],
    }


def _summary(passed=0.0, taking=0.0, failed=0.0):
    return {
        "passedCredits": passed,
        "takingCredits": taking,
        "failedCredits": failed,
        "passedSubModuleNum": 0,
        "inCredits": 0,
        "logicCredits": 0,
    }


#: 与桌面端测试同源的模型：总要求 175，含在修与未通过（UNREPAIRED）。
MODEL = {
    "id": 123456,
    "requireInfo": {"credits": 175, "subModuleNum": 4},
    "completionSummary": _summary(passed=102.5, taking=24.0, failed=72.5),
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


def _page_html() -> str:
    return "<html><script>var model = " + _as_js(MODEL) + ";</script></html>"


# ---------------------------------------------------------------------------
# JS 字面量解析一致性
# ---------------------------------------------------------------------------


def test_js_literal_parity() -> None:
    samples = [
        "{'a':1,'b':'x'}",
        "{credits:147,'$type':'ResultType'}",
        r"'\u5FC5\u4FEE\u8BFE'",
        r"'it\'s ok'",
        "{a:[1,2,{b:null,c:true}]}",
        "[-1.5, 2e3, ]",
        "{a:1,}",
    ]
    for sample in samples:
        assert mobile.parse_js_literal(sample) == desktop_js(sample), sample


def test_js_literal_rejects_non_literals() -> None:
    for bad in ("new Date()", "someVariable", "function(){}", "{a: alert(1)}", "{a:1", "[1,2", ""):
        for parser, error in ((mobile.parse_js_literal, mobile.JsLiteralError),
                              (desktop_js, DesktopJsError)):
            try:
                parser(bad)
            except error:
                pass
            else:
                raise AssertionError(f"{parser.__module__} 应拒绝 {bad!r}")


# ---------------------------------------------------------------------------
# 计划解析一致性
# ---------------------------------------------------------------------------


def test_plan_parity_with_desktop() -> None:
    html = _page_html()
    m = mobile.summarize_plan(mobile.parse_plan_page(html))
    d = desktop_parse_page(html)

    assert m["id"] == d.id
    assert m["required_credits"] == d.required_credits == 175.0
    assert m["required_sub_modules"] == d.required_sub_modules == 4
    assert m["passed_credits"] == d.passed_credits == 102.5
    assert m["taking_credits"] == d.taking_credits == 24.0
    assert m["failed_credits"] == d.failed_credits == 72.5
    assert m["missing"] == d.missing == 72.5
    assert m["ratio"] == round(d.ratio, 10) or abs(m["ratio"] - d.ratio) < 1e-9

    assert [x["name"] for x in m["modules"]] == [x.name for x in d.modules]

    for got, want in zip(m["modules"], d.modules):
        assert got["name"] == want.name
        assert got["required_credits"] == want.required_credits
        assert got["passed_credits"] == want.passed_credits
        assert got["taking_credits"] == want.taking_credits
        assert got["failed_credits"] == want.failed_credits
        assert got["missing"] == want.missing
        assert got["done"] == want.done
        assert [c["code"] for c in got["courses"]] == [c.code for c in want.courses]

    # 模块学分之和必须等于总要求
    assert sum(x["required_credits"] for x in m["modules"]) == m["required_credits"]


def test_course_result_classification_parity() -> None:
    html = _page_html()
    m = mobile.summarize_plan(mobile.parse_plan_page(html))
    d = desktop_parse_page(html)

    m_courses = {c["code"]: c for mod in m["modules"] for c in mod["courses"]}
    d_courses = {c.code: c for mod in d.modules for c in mod.courses}
    assert set(m_courses) == set(d_courses)

    for code, course in m_courses.items():
        want = d_courses[code]
        assert course["passed"] == want.passed, code
        assert course["failed"] == want.failed, code
        assert course["taking"] == want.taking, code
        assert course["result"] == want.result, code
        assert tuple(course["terms"]) == want.terms, code


def test_failed_and_taking_lists_parity() -> None:
    html = _page_html()
    m = mobile.summarize_plan(mobile.parse_plan_page(html))
    d = desktop_parse_page(html)

    # 真实的未通过取值是 UNREPAIRED；只匹配 FAILED 会一门都列不出来
    assert [c["code"] for c in m["failed_courses"]] == [
        c.code for c in d.failed_courses
    ] == ["022015"]
    assert sorted(c["code"] for c in m["taking_courses"]) == sorted(
        c.code for c in d.taking_courses
    ) == ["022056", "023031", "331002"]
    # 课程要带上所属模块，便于界面标注
    assert all(c["module"] for c in m["failed_courses"])
    assert all(c["module"] for c in m["taking_courses"])


def test_nested_modules_kept() -> None:
    child = _module(
        116340,
        "实践教学",
        25,
        [_course("025032", "毕业设计", 16, "TAKING", term=8)],
        _summary(taking=16.0),
    )
    model = {**MODEL, "moduleList": [dict(MODEL["moduleList"][0], children=[child]),
                                     *MODEL["moduleList"][1:]]}
    html = "<html><script>var model = " + _as_js(model) + ";</script></html>"

    m = mobile.parse_plan_page(html)
    d = desktop_parse_page(html)
    m_names = [x["name"] for x in m["modules"]]
    d_names = [x.name for x in d.modules]
    assert m_names == d_names
    assert "必修课" in m_names and "实践教学" in m_names
    assert m_names.index("必修课") < m_names.index("实践教学")


def test_empty_module_note_parity() -> None:
    model = {**MODEL}
    model["moduleList"] = [*MODEL["moduleList"]]
    model["moduleList"][1] = dict(MODEL["moduleList"][1])
    model["moduleList"][1]["requireInfo"] = {"credits": 12, "subModuleNum": 0}
    html = "<html><script>var model = " + _as_js(model) + ";</script></html>"

    m = mobile.parse_plan_page(html)
    d = desktop_parse_page(html)
    m_mod = next(x for x in m["modules"] if x["name"] == "校_任选课")
    d_mod = next(x for x in d.modules if x.name == "校_任选课")
    assert m_mod["required_credits"] == d_mod.required_credits == 12.0
    assert m_mod["note"] == d_mod.note
    assert "未列出课程" in m_mod["note"]


def test_rejects_bad_input() -> None:
    for bad in ("<html>空</html>", "<script>var model = {};</script>"):
        try:
            mobile.parse_plan_page(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"应拒绝 {bad!r}")

    for bad in ([], "x", 42, None, {"requireInfo": {}}):
        try:
            mobile.parse_plan(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"应拒绝 {bad!r}")


def test_desktop_page_without_model_still_fails() -> None:
    """桌面端在没有 model 时也必须报错，两端行为一致。"""
    from zzupy.plan import PlanParseError

    try:
        desktop_parse_page("<html>空</html>")
    except PlanParseError:
        pass
    else:
        raise AssertionError("桌面端应报 PlanParseError")


def test_semester_grouping() -> None:
    """课程要按学期分组，带上绩点与平均绩点。"""
    plan = mobile.summarize_plan(mobile.parse_plan_page(_page_html()))
    semesters = plan["semesters"]
    labels = [s["label"] for s in semesters]
    assert labels == ["第 1 学期", "第 3 学期", "第 4 学期", "第 7 学期"], labels

    by_term = {s["semester"]: s for s in semesters}

    # 第 4 学期：大学英语（84/3.2，通过）、电气工程导论（90/无绩点，通过）、
    # 微机原理（在修，无分）、电磁场（未通过，45/0.0）
    term4 = by_term[4]
    assert term4["course_count"] == 4
    assert term4["failed_count"] == 1
    assert term4["taking_count"] == 1
    assert term4["passed_count"] == 2
    # 只有「通过且有绩点」的课参与平均，所以只有大学英语的 3.2
    assert term4["average_gp"] == 3.2
    # 已通过学分 = 大学英语 2 + 电气工程导论 1
    assert term4["earned_credits"] == 3.0

    # 每门课都要带成绩、绩点与状态
    english = next(c for c in term4["courses"] if c["code"] == "371061")
    assert english["score"] == "84"
    assert english["gp"] == 3.2
    assert english["status"] == "passed"
    assert english["module"] == "必修课"

    taking = next(c for c in term4["courses"] if c["code"] == "022056")
    assert taking["status"] == "taking"
    assert taking["gp"] is None

    failed = next(c for c in term4["courses"] if c["code"] == "022015")
    assert failed["status"] == "failed"
    assert failed["gp"] == 0.0

    # 第 1 学期只有国家安全教育（在修）
    term1 = by_term[1]
    assert term1["taking_count"] == 1
    assert term1["average_gp"] is None
    assert term1["earned_credits"] == 0.0

    # 第 3 学期的体育（III）通过了但没有绩点 → 平均绩点必须是 None，
    # 不能是 0（0 会被误读成成绩很差）。
    term3 = by_term[3]
    assert term3["passed_count"] == 1
    assert term3["average_gp"] is None

    # 必修课要排在选修课前面（便于先看主要课程）
    term4_names = [c["name"] for c in term4["courses"]]
    assert term4_names[0] == "大学英语（IV）", term4_names


def test_semester_grouping_multi_term_course() -> None:
    """一门课横跨多个学期时，每个学期各出现一次。"""
    course = _course("12801", "形势与政策", 2, "TAKING")
    course["terms"] = [
        {"$type": "Term", "$name": f"TERM_{t}"} for t in (3, 4, 5, 6, 8)
    ]
    model = {**MODEL}
    model["moduleList"] = [
        _module(112940, "必修课", 147, [course], _summary(taking=2.0)),
    ]
    plan = mobile.summarize_plan(mobile.parse_plan_page(
        "<html><script>var model = " + _as_js(model) + ";</script></html>"
    ))
    terms = [s["semester"] for s in plan["semesters"]]
    assert terms == [3, 4, 5, 6, 8], terms
    for semester in plan["semesters"]:
        assert semester["course_count"] == 1
        assert semester["courses"][0]["planned_term"] == semester["semester"]


def test_semester_grouping_without_terms() -> None:
    """没有学期信息的课程不能丢，要归入「未标注学期」。"""
    course = _course("999999", "没学期信息的课", 1, "PASSED", score="80", gp=3.0)
    course["terms"] = []
    model = {**MODEL}
    model["moduleList"] = [
        _module(112940, "必修课", 147, [course], _summary(passed=1.0)),
    ]
    plan = mobile.summarize_plan(mobile.parse_plan_page(
        "<html><script>var model = " + _as_js(model) + ";</script></html>"
    ))
    assert len(plan["semesters"]) == 1
    assert plan["semesters"][0]["label"] == "未标注学期"
    assert plan["semesters"][0]["courses"][0]["code"] == "999999"


def test_semester_dedupes_same_course_across_modules() -> None:
    """同一门课被多个模块列出时，同一学期里只出现一次。"""
    course = _course("025032", "毕业设计", 16, "TAKING", term=8)
    model = {**MODEL}
    model["moduleList"] = [
        _module(112940, "必修课", 147, [course], _summary(taking=16.0)),
        _module(116340, "实践教学", 0, [dict(course)], _summary(taking=16.0)),
    ]
    plan = mobile.summarize_plan(mobile.parse_plan_page(
        "<html><script>var model = " + _as_js(model) + ";</script></html>"
    ))
    term8 = next(s for s in plan["semesters"] if s["semester"] == 8)
    assert term8["course_count"] == 1, [c["code"] for c in term8["courses"]]


def test_semester_average_gp_is_credit_weighted() -> None:
    """平均绩点必须按学分加权，不能是算术平均。

    构造数据让两种算法结果明显不同：
      4 学分课 绩点 4.0，1 学分课 绩点 1.0
      算术平均 = (4.0 + 1.0) / 2 = 2.5   ← 错误
      学分加权 = (4.0*4 + 1.0*1) / (4+1) = 3.4   ← 正确
    """
    model = {**MODEL}
    model["moduleList"] = [
        _module(
            112940,
            "必修课",
            147,
            [
                _course("A001", "四学分课", 4, "PASSED", term=2, score="95", gp=4.0),
                _course("A002", "一学分课", 1, "PASSED", term=2, score="61", gp=1.0),
            ],
            _summary(passed=5.0),
        )
    ]
    plan = mobile.summarize_plan(mobile.parse_plan_page(
        "<html><script>var model = " + _as_js(model) + ";</script></html>"
    ))
    semester = plan["semesters"][0]
    assert semester["average_gp"] == 3.4, semester["average_gp"]
    assert semester["average_gp"] != 2.5, "退化成了算术平均"
    assert semester["graded_credits"] == 5.0


def test_semester_average_gp_ignores_unweightable() -> None:
    """没有绩点、在修、未通过的课都不能进入平均。"""
    model = {**MODEL}
    model["moduleList"] = [
        _module(
            112940,
            "必修课",
            147,
            [
                _course("B001", "有三学分的课", 3, "PASSED", term=2, gp=3.0, score="85"),
                _course("B002", "通过但无绩点", 2, "PASSED", term=2, score="合格"),
                _course("B003", "在修", 4, "TAKING", term=2),
                _course("B004", "未通过", 4, "UNREPAIRED", term=2, score="30", gp=0.0),
                _course("B005", "零学分课", 0, "PASSED", term=2, gp=4.0, score="90"),
            ],
            _summary(passed=5.0, taking=4.0, failed=4.0),
        )
    ]
    plan = mobile.summarize_plan(mobile.parse_plan_page(
        "<html><script>var model = " + _as_js(model) + ";</script></html>"
    ))
    semester = plan["semesters"][0]
    # 只有 B001 参与：3 学分、绩点 3.0
    assert semester["average_gp"] == 3.0, semester["average_gp"]
    assert semester["graded_credits"] == 3.0


def test_semester_average_gp_matches_official_formula() -> None:
    """与 mobile_bridge 里既有的累计绩点算法保持一致（同一套加权公式）。"""
    # 复刻 mobile_bridge.get_grades 的计算方式做交叉验证
    graded = [(4.0, 4.0), (1.0, 1.0), (3.0, 2.5)]  # (绩点, 学分)
    credits = sum(c for _, c in graded)
    expected = round(sum(g * c for g, c in graded) / credits, 4)

    model = {**MODEL}
    model["moduleList"] = [
        _module(
            112940,
            "必修课",
            147,
            [
                _course(f"C{i}", f"课{i}", credit, "PASSED", term=1, gp=gp)
                for i, (gp, credit) in enumerate(graded)
            ],
            _summary(passed=credits),
        )
    ]
    plan = mobile.summarize_plan(mobile.parse_plan_page(
        "<html><script>var model = " + _as_js(model) + ";</script></html>"
    ))
    assert abs(plan["semesters"][0]["average_gp"] - expected) < 0.001


def test_result_classification_constants() -> None:
    """三个结课结果集合的边界，防止被误改。

    真实取值只有 PASSED / UNREPAIRED / TAKING，但这里把常见变体也固定下来，
    避免以后有人「顺手简化」成只认 FAILED（那会导致未通过课程一门都列不出来）。
    """
    assert "UNREPAIRED" in mobile.FAILED_RESULTS
    assert "FAILED" in mobile.FAILED_RESULTS
    assert "PASSED" in mobile.PASSED_RESULTS
    assert "TAKING" in mobile.TAKING_RESULTS

    # 三个集合不能互相重叠
    assert not (mobile.PASSED_RESULTS & mobile.FAILED_RESULTS)
    assert not (mobile.PASSED_RESULTS & mobile.TAKING_RESULTS)
    assert not (mobile.FAILED_RESULTS & mobile.TAKING_RESULTS)

    # 空结果既不算通过也不算未通过
    assert "" not in mobile.PASSED_RESULTS
    assert "" not in mobile.FAILED_RESULTS
    assert "" not in mobile.TAKING_RESULTS

    # 与桌面端同一套语义
    from zzupy.plan import PlannedCourse

    for result in ("UNREPAIRED", "FAILED", "unrepaired"):
        assert PlannedCourse(result=result).failed is True, result
    for result in ("PASSED", "passed"):
        assert PlannedCourse(result=result).passed is True, result
    for result in ("TAKING", "taking"):
        assert PlannedCourse(result=result).taking is True, result
    assert PlannedCourse(result="").failed is False


def main() -> None:
    test_js_literal_parity()
    test_js_literal_rejects_non_literals()
    test_plan_parity_with_desktop()
    test_course_result_classification_parity()
    test_failed_and_taking_lists_parity()
    test_nested_modules_kept()
    test_empty_module_note_parity()
    test_rejects_bad_input()
    test_desktop_page_without_model_still_fails()
    test_semester_grouping()
    test_semester_grouping_multi_term_course()
    test_semester_grouping_without_terms()
    test_semester_dedupes_same_course_across_modules()
    test_semester_average_gp_is_credit_weighted()
    test_semester_average_gp_ignores_unweightable()
    test_semester_average_gp_matches_official_formula()
    test_result_classification_constants()
    print("手机端与桌面端培养计划解析完全一致，自检全部通过。")


if __name__ == "__main__":
    main()
