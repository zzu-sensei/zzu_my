"""培养计划解析与完成度统计。

数据来自本科教务学生端的「培养计划完成情况预览」页面。页面把整个模型以
**JavaScript 对象字面量**内联在 ``<script>`` 里（``var model = {...}``），
顶层字段包括::

    {
      "id": 123456,
      "requireInfo": {"credits": 175, "subModuleNum": 4},
      "completionSummary": {"passedCredits": 102.5, "failedCredits": 72.5, ...},
      "moduleList": [
        {
          "moduleId": 112940,
          "nameZh": "必修课",
          "requireInfo": {"credits": 147, "subModuleNum": 0},
          "completionSummary": {"passedCredits": 83.5, "takingCredits": 18, ...},
          "allCourseList": [
            {
              "code": "371061", "nameZh": "大学英语（IV）", "credits": 2,
              "compulsory": true, "score": 84, "gp": 3.2,
              "resultType": {"$type": "ResultType", "$name": "PASSED"},
              "terms": [{"$type": "Term", "$name": "TERM_4"}]
            }
          ]
        }
      ]
    }

三个必须注意的点，都是从真实响应里确认的：

1. **学分要求字段是 ``credits``／``subModuleNum``**，不是 ``requiredCredits``／
   ``requiredCourseNum``。不同接口的命名确实不一致。
2. **每门课自带结课结果**（``resultType.$name``：``PASSED`` / ``FAILED`` /
   ``TAKING`` 等），并且页面已经算好了各模块的通过学分与在修学分。因此完成度
   **优先采用页面给出的权威数值**，再退回按成绩自行计算。
3. **``<script>`` 里的字面量是 JS 而不是 JSON**：单引号、键不加引号、键可带
   ``$``，所以必须用 :mod:`zzupy.web.jsdata` 解析。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from zzupy.web.jsdata import JsLiteralError, parse_js_literal, slice_js_object

#: 计划里没有、但已修课程中出现的课程归到这里。
OUTSIDE_PLAN_NAME = "计划外课程"

#: 及格线。成绩为数字且低于该值时视为未通过。
PASS_SCORE = 60.0

#: 页面里承载培养计划数据的变量名。
MODEL_VAR_PATTERN = re.compile(r"var\s+model\s*=\s*\{")


class PlanParseError(Exception):
    """培养计划数据结构不符合预期。"""

    def __init__(self, message: str, *, context: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.context = dict(context or {})

    def __str__(self) -> str:
        return self.message


def parse_numeric_score(value: Any) -> float | None:
    """从成绩文本里抽出数字分数。

    ``"92"``、``"92.5"`` 能抽出数字；``"良好"``、``"优秀"`` 这类等级制成绩返回
    ``None``，由调用方用绩点或结课结果判定。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value))
    return float(match.group()) if match else None


def course_passed(grade: Mapping[str, Any]) -> bool:
    """判断一条成绩记录是否已通过。

    规则（与移动端 ``mobile_plan``、``scripts/test_mobile_plan.py`` 的交叉比对
    保持一致）：

    1. 服务端给出的 ``passed`` 最可靠，优先使用；
    2. 否则看数字成绩是否达到及格线；
    3. 等级制成绩看绩点是否大于 0；
    4. 都拿不到时按**未通过**处理，宁可少算也不虚报完成度。
    """
    explicit = grade.get("passed")
    if isinstance(explicit, bool):
        return explicit
    if isinstance(explicit, str):
        lowered = explicit.strip().lower()
        if lowered in {"是", "通过", "合格", "pass", "passed", "yes", "y", "true"}:
            return True
        if lowered in {"否", "未通过", "不合格", "fail", "failed", "no", "n", "false"}:
            return False

    score = parse_numeric_score(grade.get("score"))
    if score is not None:
        return score >= PASS_SCORE

    gp = grade.get("gp")
    if gp is not None:
        try:
            return float(gp) > 0
        except (TypeError, ValueError):
            return False
    return False


# ---------------------------------------------------------------------------
# 页面模型抽取
# ---------------------------------------------------------------------------


def extract_plan_model(html: str) -> dict[str, Any] | None:
    """从培养计划页面里抽出内联的计划模型。

    页面结构是 ``var model = { ... };``，这里定位该赋值语句，按括号配平切出对象
    文本，再用 JS 字面量解析器解析。

    Args:
        html: 页面 HTML。

    Returns:
        计划模型字典；页面里找不到时返回 ``None``。
    """
    for match in MODEL_VAR_PATTERN.finditer(html):
        brace = html.index("{", match.start())
        text = slice_js_object(html, brace)
        if text is None:
            continue
        try:
            parsed = parse_js_literal(text)
        except JsLiteralError:
            # 这个 model 不是可解析的数据字面量，继续找下一个。
            continue
        if isinstance(parsed, dict) and "moduleList" in parsed:
            return parsed
    return None


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _result_name(value: Any) -> str:
    """从 ``{"$type": "ResultType", "$name": "PASSED"}`` 里取出结果名。"""
    if isinstance(value, Mapping):
        return str(value.get("$name") or "").strip()
    if value is None:
        return ""
    return str(value).strip()


def _terms_from(raw: Any) -> tuple[int, ...]:
    """把 ``[{"$name":"TERM_4"}]`` 或 ``["TERM_4"]`` 解析成学期序号。"""
    if not isinstance(raw, list):
        return ()
    terms: set[int] = set()
    for item in raw:
        text = _result_name(item) if isinstance(item, Mapping) else str(item)
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            terms.add(int(digits))
    return tuple(sorted(terms))


@dataclass(frozen=True)
class PlannedCourse:
    """计划内的一门课，含页面给出的结课结果。

    Args:
        code: 课程编号。
        name: 课程中文名。
        credits: 课程学分。
        compulsory: 是否必修。
        terms: 建议修读学期序号。
        result: 结课结果，``PASSED`` / ``FAILED`` / ``TAKING`` 等；未知时为空串。
        score: 成绩文本。
        gp: 绩点。
    """

    code: str = ""
    name: str = ""
    credits: float = 0.0
    compulsory: bool = False
    terms: tuple[int, ...] = ()
    result: str = ""
    score: str = ""
    gp: float | None = None

    @property
    def failed(self) -> bool:
        """是否未通过。

        教务的实际取值是 ``UNREPAIRED``（挂科未重修），不是直觉上的 ``FAILED``；
        这里把常见变体都算进去，避免因为命名不同而漏报。
        """
        return self.result.upper() in {
            "UNREPAIRED",
            "FAILED",
            "FAIL",
            "NOT_PASSED",
            "UNPASSED",
        }

    @property
    def passed(self) -> bool:
        """是否已通过（以页面的结课结果为准）。"""
        return self.result.upper() in {"PASSED", "PASS", "RECOGNIZED"}

    @property
    def taking(self) -> bool:
        """是否在修。"""
        return self.result.upper() in {"TAKING", "INPROGRESS", "IN_PROGRESS"}

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "credits": round(self.credits, 2),
            "compulsory": self.compulsory,
            "terms": list(self.terms),
            "result": self.result,
            "score": self.score,
            "gp": self.gp,
        }


@dataclass(frozen=True)
class PlanModule:
    """一个学分要求模块。

    ``passed_credits`` 等来自页面自带的 ``completionSummary``，是教务算好的权威
    数值；页面没给时才需要用成绩自行统计。
    """

    id: int
    name: str
    required_credits: float = 0.0
    required_sub_modules: int = 0
    courses: tuple[PlannedCourse, ...] = ()
    passed_credits: float = 0.0
    taking_credits: float = 0.0
    failed_credits: float = 0.0
    passed_sub_modules: int = 0
    note: str = ""

    @property
    def missing(self) -> float:
        """还差多少学分（不含在修）。"""
        return max(0.0, self.required_credits - self.passed_credits)

    @property
    def done(self) -> bool:
        """是否已达标。"""
        return self.passed_credits + 1e-9 >= self.required_credits

    @property
    def ratio(self) -> float:
        """完成比例。"""
        if self.required_credits <= 0:
            return 1.0
        return self.passed_credits / self.required_credits

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "required_credits": round(self.required_credits, 2),
            "required_sub_modules": self.required_sub_modules,
            "passed_credits": round(self.passed_credits, 2),
            "taking_credits": round(self.taking_credits, 2),
            "failed_credits": round(self.failed_credits, 2),
            "passed_sub_modules": self.passed_sub_modules,
            "missing": round(self.missing, 2),
            "done": self.done,
            "ratio": round(self.ratio, 4),
            "courses": [item.to_dict() for item in self.courses],
            "note": self.note,
        }


@dataclass(frozen=True)
class TrainingPlan:
    """一份培养计划。"""

    id: int
    required_credits: float = 0.0
    required_sub_modules: int = 0
    modules: tuple[PlanModule, ...] = ()
    passed_credits: float = 0.0
    taking_credits: float = 0.0
    failed_credits: float = 0.0
    #: 页面未提供汇总时，回退到按成绩自行统计。
    fallback_passed_credits: float | None = None

    @property
    def effective_passed_credits(self) -> float:
        """已通过学分：优先页面汇总，其次自行统计。"""
        if self.passed_credits or self.taking_credits or self.failed_credits:
            return self.passed_credits
        if self.fallback_passed_credits is not None:
            return self.fallback_passed_credits
        return self.passed_credits

    @property
    def missing(self) -> float:
        """还差多少学分。"""
        return max(0.0, self.required_credits - self.effective_passed_credits)

    @property
    def ratio(self) -> float:
        """完成比例。"""
        if self.required_credits <= 0:
            return 0.0
        return self.effective_passed_credits / self.required_credits

    @property
    def module_credits(self) -> float:
        """各模块要求学分之和，用于和总学分核对。"""
        return sum(item.required_credits for item in self.modules)

    def courses_with_result(self, *results: str) -> tuple[PlannedCourse, ...]:
        """按结课结果筛出计划课程（去重、保持出现顺序）。

        Args:
            results: 结课结果名，如 ``"FAILED"``、``"TAKING"``。
        """
        wanted = {name.upper() for name in results}
        seen: set[tuple[str, str]] = set()
        found: list[PlannedCourse] = []
        for module in self.modules:
            for course in module.courses:
                if course.result.upper() not in wanted:
                    continue
                key = (course.code or course.name, course.name)
                if key in seen:
                    continue
                seen.add(key)
                found.append(course)
        return tuple(found)

    @property
    def failed_courses(self) -> tuple[PlannedCourse, ...]:
        """未通过的课程。

        真实的结课结果是 ``UNREPAIRED``（挂科未重修），因此不能只匹配 ``FAILED``。
        """
        return self.courses_with_result(
            "UNREPAIRED", "FAILED", "FAIL", "NOT_PASSED", "UNPASSED"
        )

    @property
    def taking_courses(self) -> tuple[PlannedCourse, ...]:
        """在修课程。"""
        return self.courses_with_result("TAKING", "INPROGRESS", "IN_PROGRESS")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "required_credits": round(self.required_credits, 2),
            "required_sub_modules": self.required_sub_modules,
            "passed_credits": round(self.effective_passed_credits, 2),
            "taking_credits": round(self.taking_credits, 2),
            "failed_credits": round(self.failed_credits, 2),
            "missing": round(self.missing, 2),
            "ratio": round(self.ratio, 4),
            "modules": [item.to_dict() for item in self.modules],
        }


# ---------------------------------------------------------------------------
# 解析
# ---------------------------------------------------------------------------


def _parse_course(raw: Any) -> PlannedCourse | None:
    """解析 ``allCourseList`` 里的一个课程条目。"""
    if not isinstance(raw, Mapping):
        return None
    name = str(raw.get("nameZh") or raw.get("name") or "").strip()
    code = str(raw.get("code") or "").strip()
    if not name and not code:
        return None
    gp_raw = raw.get("gp")
    gp: float | None
    try:
        gp = None if gp_raw is None else float(gp_raw)
    except (TypeError, ValueError):
        gp = None
    return PlannedCourse(
        code=code,
        name=name,
        credits=_to_float(raw.get("credits")),
        compulsory=bool(raw.get("compulsory")),
        terms=_terms_from(raw.get("terms")),
        result=_result_name(raw.get("resultType") or raw.get("finalResultType")),
        score=str(raw.get("gradeStr") or raw.get("score") or "").strip(),
        gp=gp,
    )


def _summary_of(node: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = node.get("completionSummary")
    return summary if isinstance(summary, Mapping) else {}


def _collect_modules(node: Mapping[str, Any]) -> list[PlanModule]:
    """递归收集学分模块。

    父模块与子模块都是独立的学分桶，因此**不能**因为节点有子模块就跳过它本身：
    「必修课」要求 147 学分，下面还可能挂子模块，跳掉父节点会直接丢掉要求学分。
    这里每个节点只产出一份，不会重复计数。
    """
    name = str(node.get("nameZh") or node.get("name") or "").strip()
    if not name:
        return []

    raw_courses = node.get("allCourseList") or node.get("courseList")
    courses = tuple(
        course
        for course in (
            _parse_course(item)
            for item in (raw_courses if isinstance(raw_courses, list) else [])
        )
        if course is not None
    )

    info = node.get("requireInfo")
    info = info if isinstance(info, Mapping) else {}
    required_credits = _to_float(info.get("credits"))
    required_sub_modules = _to_int(info.get("subModuleNum"))
    summary = _summary_of(node)

    collected: list[PlanModule] = []
    if courses or required_credits > 0:
        note = ""
        if required_credits > 0 and not courses:
            note = "该模块未列出课程，无法逐课核对，以教务系统为准"
        collected.append(
            PlanModule(
                id=_to_int(node.get("moduleId") or node.get("id")),
                name=name,
                required_credits=required_credits,
                required_sub_modules=required_sub_modules,
                courses=courses,
                passed_credits=_to_float(summary.get("passedCredits")),
                taking_credits=_to_float(summary.get("takingCredits")),
                failed_credits=_to_float(summary.get("failedCredits")),
                passed_sub_modules=_to_int(summary.get("passedSubModuleNum")),
                note=note,
            )
        )

    children = node.get("children")
    for child in children if isinstance(children, list) else []:
        if isinstance(child, Mapping):
            collected.extend(_collect_modules(child))
    return collected


def parse_plan(payload: Any) -> TrainingPlan:
    """把页面模型解析成结构化的培养计划。

    Raises:
        PlanParseError: 顶层不是对象，或缺少可识别的模块与学分要求。
    """
    if not isinstance(payload, Mapping):
        raise PlanParseError(
            "培养计划响应不是对象",
            context={"type": type(payload).__name__},
        )

    info = payload.get("requireInfo")
    info = info if isinstance(info, Mapping) else {}
    summary = _summary_of(payload)

    raw_modules = payload.get("moduleList")
    modules: list[PlanModule] = []
    for item in raw_modules if isinstance(raw_modules, list) else []:
        if isinstance(item, Mapping):
            modules.extend(_collect_modules(item))

    if not modules:
        raise PlanParseError(
            "培养计划里没有可识别的学分模块",
            context={"keys": sorted(payload.keys())[:20]},
        )

    return TrainingPlan(
        id=_to_int(payload.get("id")),
        required_credits=_to_float(info.get("credits")),
        required_sub_modules=_to_int(info.get("subModuleNum")),
        modules=tuple(modules),
        passed_credits=_to_float(summary.get("passedCredits")),
        taking_credits=_to_float(summary.get("takingCredits")),
        failed_credits=_to_float(summary.get("failedCredits")),
    )


def parse_plan_page(html: str) -> TrainingPlan:
    """直接从培养计划页面 HTML 得到计划。

    Raises:
        PlanParseError: 页面里找不到计划模型。
    """
    model = extract_plan_model(html)
    if model is None:
        raise PlanParseError(
            "未能从页面解析出培养计划模型（页面结构可能已更新）",
            context={"length": len(html)},
        )
    return parse_plan(model)


# ---------------------------------------------------------------------------
# 与成绩对照（页面未提供结课结果时使用）
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CourseMatch:
    """一门已修课程与计划的对照结果。"""

    code: str
    name: str
    credits: float
    passed: bool
    module: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "credits": round(self.credits, 2),
            "passed": self.passed,
            "module": self.module,
        }


@dataclass(frozen=True)
class PlanCompletion:
    """按成绩自行统计的完成度（页面无汇总时的回退口径）。"""

    plan_id: int
    required_credits: float
    earned_credits: float
    outside_plan: tuple[CourseMatch, ...] = ()
    failed: tuple[CourseMatch, ...] = ()
    per_module: tuple[tuple[str, float], ...] = ()

    @property
    def outside_plan_credits(self) -> float:
        """计划外已通过学分。"""
        return sum(item.credits for item in self.outside_plan if item.passed)

    @property
    def missing(self) -> float:
        return max(0.0, self.required_credits - self.earned_credits)

    @property
    def ratio(self) -> float:
        if self.required_credits <= 0:
            return 0.0
        return self.earned_credits / self.required_credits

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "required_credits": round(self.required_credits, 2),
            "earned_credits": round(self.earned_credits, 2),
            "missing": round(self.missing, 2),
            "ratio": round(self.ratio, 4),
            "outside_plan": [item.to_dict() for item in self.outside_plan],
            "outside_plan_credits": round(self.outside_plan_credits, 2),
            "failed": [item.to_dict() for item in self.failed],
            "per_module": [
                {"module": name, "earned_credits": round(value, 2)}
                for name, value in self.per_module
            ],
        }


def match_completion(
    plan: TrainingPlan,
    grades: Iterable[Mapping[str, Any]],
    *,
    passed_of: Any = course_passed,
) -> PlanCompletion:
    """把已修成绩与计划课程对照，算出学分。

    计划内学分**只统计出现在计划课程里的课**；计划外的课单独列出，不计入，
    避免完成度虚高。

    Args:
        plan: 已解析的培养计划。
        grades: 成绩记录，需含课程名与学分；可选课程编号。
        passed_of: 判定某条成绩是否通过的函数。
    """
    code_index: dict[str, PlanModule] = {}
    name_index: dict[str, PlanModule] = {}
    for module in plan.modules:
        for course in module.courses:
            if course.code:
                code_index.setdefault(course.code, module)
            if course.name:
                name_index.setdefault(course.name, module)

    # 同一门课重修多次，按课程归并后只计最好的一次。
    best: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for grade in grades:
        name = str(
            grade.get("course") or grade.get("course_name_zh") or "未知课程"
        ).strip()
        code = str(grade.get("code") or grade.get("course_code") or "").strip()
        key = f"{code}\u0001{name}" if code else name
        if key not in best:
            order.append(key)
            best[key] = {
                "name": name,
                "code": code,
                "credits": _to_float(grade.get("credits")),
                "passed": bool(passed_of(grade)),
            }
            continue
        record = best[key]
        passed_now = bool(passed_of(grade))
        credits = _to_float(grade.get("credits"))
        if passed_now and not record["passed"]:
            record["passed"] = True
            record["credits"] = credits
        elif passed_now and record["passed"]:
            record["credits"] = max(record["credits"], credits)

    earned: dict[int, float] = {module.id: 0.0 for module in plan.modules}
    outside: list[CourseMatch] = []
    failed: list[CourseMatch] = []

    for key in order:
        record = best[key]
        name, code, credits = record["name"], record["code"], record["credits"]
        is_passed = record["passed"]

        module = code_index.get(code) if code else None
        if module is None:
            module = name_index.get(name)

        if module is None:
            outside.append(
                CourseMatch(code=code, name=name, credits=credits, passed=is_passed)
            )
            if not is_passed:
                failed.append(
                    CourseMatch(code=code, name=name, credits=credits, passed=False)
                )
            continue

        if is_passed:
            earned[module.id] += credits
        else:
            failed.append(
                CourseMatch(
                    code=code, name=name, credits=credits, passed=False,
                    module=module.name,
                )
            )

    per_module = tuple(
        (module.name, earned[module.id]) for module in plan.modules
    )
    return PlanCompletion(
        plan_id=plan.id,
        required_credits=plan.required_credits,
        earned_credits=sum(earned.values()),
        outside_plan=tuple(outside),
        failed=tuple(failed),
        per_module=per_module,
    )


# ---------------------------------------------------------------------------
# 报告
# ---------------------------------------------------------------------------


def _bar(ratio: float, width: int) -> str:
    filled = max(0, min(int(ratio * width), width))
    return "█" * filled + "░" * (width - filled)


def format_completion(plan: TrainingPlan, *, width: int = 24) -> str:
    """把完成度渲染成便于阅读的多行文本。

    学分以**页面自带的权威汇总**为准；同时在修与未通过学分单独标出，因为它们
    虽然不计入已通过学分，但对「还差多少」的判断很关键。
    """
    passed = plan.effective_passed_credits
    lines = [
        f"培养计划完成度：{passed:g} / {plan.required_credits:g} 学分"
        f"（{plan.ratio * 100:.1f}%），还差 {plan.missing:g} 学分",
    ]
    extras = []
    if plan.taking_credits:
        extras.append(f"在修 {plan.taking_credits:g}")
    if plan.failed_credits:
        extras.append(f"未通过 {plan.failed_credits:g}")
    if extras:
        lines.append("（" + "，".join(extras) + " 学分未计入已通过）")
    lines.append("")

    for module in plan.modules:
        line = (
            f"{module.name:<10} {_bar(module.ratio, width)} "
            f"{module.passed_credits:>6.1f}/{module.required_credits:<6.1f} "
        )
        if module.done:
            line += "已达标"
        else:
            line += f"还差 {module.missing:g}"
        if module.taking_credits:
            line += f"（在修 {module.taking_credits:g}）"
        lines.append(line)
        if module.note:
            lines.append(f"{'':<10} 注：{module.note}")

    failed = plan.failed_courses
    if failed:
        names = "、".join(f"{c.name}({c.credits:g})" for c in failed[:10])
        more = "…" if len(failed) > 10 else ""
        lines.extend(["", f"未通过 {len(failed)} 门：{names}{more}"])

    taking = plan.taking_courses
    if taking:
        names = "、".join(f"{c.name}({c.credits:g})" for c in taking[:10])
        more = "…" if len(taking) > 10 else ""
        lines.extend(["", f"在修 {len(taking)} 门：{names}{more}"])

    if failed or taking:
        lines.extend(
            [
                "",
                "注：上面的学分以教务给出的模块汇总为准；下面课程清单是按每门课的"
                "结课结果统计的，口径不同（例如同一门课在不同模块各列一次），"
                "两者可能略有差异。",
            ]
        )
    return "\n".join(lines)


__all__ = [
    "CourseMatch",
    "MODEL_VAR_PATTERN",
    "OUTSIDE_PLAN_NAME",
    "PASS_SCORE",
    "PlanCompletion",
    "PlanModule",
    "PlanParseError",
    "PlannedCourse",
    "TrainingPlan",
    "course_passed",
    "extract_plan_model",
    "format_completion",
    "match_completion",
    "parse_numeric_score",
    "parse_plan",
    "parse_plan_page",
]
