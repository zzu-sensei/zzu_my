"""诊断培养计划页面的内嵌数据结构（离线分析）。

把教务返回的页面存成文件后，用它确认计划数据以什么形式嵌入：标准 JSON、
JS 对象字面量、还是转义在字符串里。页面模板一变就得靠这个定位。

配合 ``dev/session.py`` 抓页面：

    .venv\\Scripts\\python.exe scripts/dev/session.py <页面URL>   # 抓取
    .venv\\Scripts\\python.exe scripts/dev/diagnose_plan_page.py <页面文件>

不需要登录，也不联网。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from zzupy.plan import PlanParseError, extract_plan_model, parse_plan_page  # noqa: E402
from zzupy.web.jsdata import JsLiteralError, parse_js_literal, slice_js_object  # noqa: E402

#: 计划模型里必然出现的字段，用来判断抽到的是不是想要的对象。
REQUIRED_KEYS = ("requireInfo", "moduleList")

#: 页面里承载计划数据的变量名。
MODEL_VAR = re.compile(r"var\s+model\s*=\s*\{")


def show(label: str, text: str, *, limit: int = 600) -> None:
    body = text[:limit] + ("..." if len(text) > limit else "")
    print(f"\n=== {label} ===")
    print(body)


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: diagnose_plan_page.py <页面文件路径>")
        raise SystemExit(2)

    path = Path(sys.argv[1])
    if not path.is_file():
        print(f"文件不存在: {path}")
        raise SystemExit(2)

    html = path.read_text(encoding="utf-8", errors="replace")
    print(f"文件: {path}")
    print(f"长度: {len(html)} 字符")

    # 1) 关键字段出现次数：反映数据是否真的在页面里
    print("\n=== 关键字段出现次数 ===")
    for field in ("requireInfo", "moduleList", "allCourseList", "completionSummary",
                  "planCourses", "requiredCredits"):
        count = len(re.findall(re.escape(field), html))
        print(f"  {field:<20} {count}")

    # 2) 形态判断
    print("\n=== 形态判断 ===")
    checks = {
        "含转义 \\\"": '\\"' in html,
        "含单引号键 'requireInfo'": "'requireInfo'" in html,
        "含无引号键 requireInfo:": "requireInfo:" in html,
        "含 &quot;": "&quot;" in html,
        "含 var model = {": bool(MODEL_VAR.search(html)),
    }
    for label, hit in checks.items():
        print(f"  {label}: {hit}")

    # 3) 定位 var model 并尝试解析
    print("\n=== 尝试解析计划模型 ===")
    match = MODEL_VAR.search(html)
    if not match:
        print("  未找到 var model = {...}，页面结构可能已更新。")
        print("  提示：若数据是前端另发 XHR 取的，需要在 Network 面板找接口路径。")
        raise SystemExit(1)

    brace = html.find("{", match.start())
    snippet = slice_js_object(html, brace)
    print(f"  var model 位置: {match.start()}，切出对象长度: {len(snippet) if snippet else None}")
    if not snippet:
        print("  括号不配平，无法切出对象。")
        raise SystemExit(1)

    if "requireInfo" not in snippet:
        print("  切出的对象里没有 requireInfo，可能切到了内层对象。")

    try:
        parsed = parse_js_literal(snippet)
    except JsLiteralError as exc:
        print(f"  JS 字面量解析失败: {exc}")
        position = exc.position or 0
        show("失败位置上下文", snippet[max(0, position - 200):position + 200])
        raise SystemExit(1)

    if not isinstance(parsed, dict):
        print(f"  解析结果不是对象，而是 {type(parsed).__name__}")
        raise SystemExit(1)

    missing = [key for key in REQUIRED_KEYS if key not in parsed]
    print(f"  解析成功，顶层键: {sorted(parsed.keys())}")
    if missing:
        print(f"  缺少预期字段: {missing}")

    # 4) 端到端
    print("\n=== 端到端解析 ===")
    model = extract_plan_model(html)
    print(f"  extract_plan_model: {'成功' if model else '失败'}")
    try:
        plan = parse_plan_page(html)
    except PlanParseError as exc:
        print(f"  parse_plan_page 失败: {exc.message}")
        print(f"  上下文: {exc.context}")
        raise SystemExit(1)

    print(f"  总要求学分: {plan.required_credits}")
    print(f"  已通过: {plan.passed_credits}  在修: {plan.taking_credits}"
          f"  未通过: {plan.failed_credits}")
    print(f"  模块数: {len(plan.modules)}")
    for module in plan.modules:
        print(f"    {module.name:<12} {module.passed_credits:>6.1f}/"
              f"{module.required_credits:<6.1f} 课程 {len(module.courses)} 门")
    print(f"  未通过课程: {len(plan.failed_courses)} 门")
    print(f"  在修课程: {len(plan.taking_courses)} 门")

    total = plan.module_credits
    flag = "一致" if abs(total - plan.required_credits) < 1e-6 else "不一致！"
    print(f"\n  模块学分之和 {total} 与总要求 {plan.required_credits} {flag}")


if __name__ == "__main__":
    main()
