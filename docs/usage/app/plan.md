# 培养计划完成情况

`zzupy.plan` 解析本科教务学生端的「培养计划完成情况预览」，给出**官方**的学分
要求、各模块完成度、未通过在修课程清单。

!!! tip "数据全部来自教务，不需要手工填任何东西"
    学分要求、计划课程、完成度汇总都由教务页面给出，不用维护配置文件，也不用
    猜课程归属类别。

## 快速开始

```bash
zzu --account 你的学号 plan
zzu --account 你的学号 plan --json
# 指定学生内部 ID（不传时由教务按当前登录学生跳转）
zzu --account 你的学号 plan --program-id 123456
```

输出形如：

```
培养计划完成度：102.5 / 175 学分（58.6%），还差 72.5 学分
（在修 24，未通过 72.5 学分未计入已通过）

必修课        █████████████░░░░░░░░░░░   83.5/147.0  还差 63.5（在修 18）
校_任选课      ████████████████████████    6.0/5.0    已达标
院_任选课      ██████████████░░░░░░░░░░    7.0/12.0   还差 5（在修 4）
限选课        ███████████████░░░░░░░░░    7.0/11.0   还差 4（在修 2）

未通过 20 门：电路实验(1.5)、电子实验(1)、电力电子技术(3)…
在修 12 门：自动控制理论(4)、电工实践(1)、电子技术课程设计(1)…
```

## 在代码里使用

```python
from zzupy.app import CASClient
from zzupy.plan import format_completion, parse_plan_page
from zzupy.web import StudentWebEASClient

cas = CASClient("your_account", "your_password")
cas.login()

with StudentWebEASClient(cas) as web:
    web.login()
    plan = web.get_program_plan()        # 已解析好的 TrainingPlan

print(format_completion(plan))
for module in plan.modules:
    print(module.name, module.passed_credits, "/", module.required_credits)
```

页面 HTML 也直接可用：

```python
plan = parse_plan_page(html)
```

## 页面结构（为什么不能用 `json.loads`）

计划数据以 **JavaScript 对象字面量**内联在 `<script>var model = {...}</script>` 里，
写法是 JS 而不是 JSON：

```javascript
var model = {
  id: 123456,
  requireInfo: {credits: 175, subModuleNum: 4},
  completionSummary: {passedCredits: 102.5, failedCredits: 72.5, takingCredits: 24},
  moduleList: [
    {
      moduleId: 112940,
      nameZh: '必修课',
      requireInfo: {credits: 147, subModuleNum: 0},
      completionSummary: {passedCredits: 83.5, takingCredits: 18, failedCredits: 63.5},
      allCourseList: [
        {
          code: '371061', nameZh: '大学英语（IV）', credits: 2, compulsory: true,
          score: 84, gp: 3.2,
          resultType: {$type: 'ResultType', $name: 'PASSED'},
          terms: [{$type: 'Term', $name: 'TERM_4'}],
        },
      ],
    },
  ],
};
```

因此 [`zzupy.web.jsdata`][zzupy.web.jsdata] 提供了一个**只解析数据字面量**的
解析器：支持单引号、裸键、`$` 开头的键、`\uXXXX` 转义；遇到函数、变量引用、
表达式一律报错，**绝不求值**，不会把页面里任意 JS 当代码执行。

## 五个实际踩出来的要点

这些都是对着真实响应确认过的，不是推测：

1. **学分要求字段是 `credits` / `subModuleNum`**，不是 `requiredCredits` /
   `requiredCourseNum`。同一个教务系统里不同接口的命名并不统一。
2. **未通过的取值是 `UNREPAIRED`**（挂科未重修），不是直觉上的 `FAILED`。
   只匹配 `FAILED` 会一门课程都列不出来。三种实际取值：`PASSED`、`UNREPAIRED`、
   `TAKING`。
3. **父模块和子模块都是独立学分桶。** 不能因为节点有子模块就跳过它本身，否则
   会丢掉「必修课」的 147 学分。`parse_plan` 每个节点只产出一份。
4. **完成度优先采用页面汇总。** 页面 `completionSummary` 已经算好各模块的
   通过／在修／未通过学分，这是教务官方口径，比自行统计成绩更权威。
5. **课程清单与汇总的口径不同。** 按每门课的结课结果累加会与模块汇总略有差异
   （同一门课可能在不同模块各列一次）。报告里以**汇总为准**，并明确标注这一点。

## 字段说明

### `TrainingPlan`

| 字段 | 含义 |
| --- | --- |
| `id` | 学生内部 ID（出现在 URL 里，例如 `.../info/123456`） |
| `required_credits` | 总要求学分 |
| `required_sub_modules` | 需要修满的模块个数 |
| `passed_credits` | 已通过学分（页面汇总） |
| `taking_credits` | 在修学分 |
| `failed_credits` | 未通过学分 |
| `missing` / `ratio` | 还差多少学分 / 完成比例 |
| `modules` | 各学分模块 |
| `failed_courses` / `taking_courses` | 未通过 / 在修课程清单 |

### `PlanModule`

`id`、`name`、`required_credits`、`passed_credits`、`taking_credits`、
`failed_credits`、`courses`、`note`。模块给出要求学分却不列课程时，`note` 会
说明「以教务系统为准」，而不是假装数据完整。

### `PlannedCourse`

`code`、`name`、`credits`、`compulsory`、`terms`、`result`、`score`、`gp`，
并提供 `passed` / `failed` / `taking` 三个判定属性。

## 在桌面端使用

`zzu-gui` 的「成绩」页有「培养计划完成情况」面板，点「统计」即可，报告显示在
下方文本框里。

## 在安卓端使用

安卓端有**独立页面**：底部导航「成绩」入口里切到「培养计划」标签即可。

页面上方是总完成度（已通过 / 总要求学分、进度条、还差多少），下面可在两种视图间切换：

**按学期**（默认）——每门课按它自己的修读学期分组，学期卡片显示

- 学期名、课程门数、已通过学分；
- **该学期平均绩点**（只统计「已通过且有绩点」的课程）；
- 有未通过/在修时卡片会高亮，并标出门数；
- 展开后逐门课显示 **课程名、学分、所属模块、成绩、绩点**，用颜色区分
  通过 / 在修 / 未通过。

默认只展开最早一个还有未通过或在修的学期，其余收起，避免一屏过长。

**按学分模块**——各模块的要求学分与完成度。

学期来自课程自己的 `terms` 字段（`TERM_4` → 第 4 学期）。一门课横跨多个学期时
（如「形势与政策」跨 3/4/5/6/8 学期）会在每个学期各出现一次；没有学期信息的
课程归入「未标注学期」，不会丢弃。

手机端使用自包含解析器 `mobile_plan_page.py`（不依赖 loguru），与桌面端
`zzupy.plan` **规则完全一致**，由 `scripts/test_mobile_plan_page.py` 交叉比对：
JS 字面量解析、模块结构、结课结果归类、未通过/在修清单、嵌套模块、空模块提示、
以及学期分组（含平均绩点、跨学期课程、无学期课程、跨模块去重）都逐项核对。

??? note "`mobile_plan.py` 与 `mobile_plan_page.py` 的区别"
    `mobile_plan.py` 是早期按关键词归类、手填要求学分的实现；`mobile_plan_page.py`
    是接入教务真实计划的新实现，供「培养计划」页面使用。前者保留为兼容路径，
    不再扩展。

## 关于「计划外课程」

模型里还有 `outerCourseList`（计划外课程学分认定记录）和 `outerCompletionSummary`，
属于另一套认定流程，目前**没有**纳入完成度统计——计划外课程必须走学校的认定
申请才会计入，直接算进去会误导。

## 相关模块

- [`zzupy.plan`][zzupy.plan]：计划解析、完成度统计与报告渲染
- [`zzupy.web.jsdata`][zzupy.web.jsdata]：JS 数据字面量解析
- [`zzupy.web.eas`][zzupy.web.eas]：`StudentWebEASClient.get_program_plan()`
