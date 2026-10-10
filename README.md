# ZZU.Py / 郑大生活助手

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.11-blue.svg)](pyproject.toml)

豫见郑大相关服务的 Python API 封装与网页端。安卓客户端见
[zzu-life-android](https://github.com/zzu-sensei/zzu-life-android)。

> [!IMPORTANT]
> 本项目由社区独立维护，与郑州大学及相关服务提供方无隶属或授权关系。接口可能随学校系统调整而失效；请仅在本人账号和授权范围内使用，并遵守学校规定。

## 概述

`zzupy` 面向郑州大学常用线上服务，提供统一、显式且带类型提示的 Python 客户端。当前主要覆盖：

- App 端统一认证（CAS）
- 新本科教务（EAS）
- 校园一卡通
- 校园网 Portal 认证与自助服务系统
- 对应的异步实现

> [!WARNING]
> 当前仅适配本科教务新系统，研究生教务暂未支持。

## 特性

- 账密登录与 Token 复用并存，适合脚本和长期任务
- 同步 / 异步 API 基本对齐，迁移成本低
- 使用 Pydantic 模型组织响应数据，便于补全和校验
- 提供统一异常层级，公共异常基类为 `zzupy.exception.ZZUError`
- 保留较底层的请求行为，尽量贴近真实上游接口

## 安装

```bash
pip install -U zzupy
```

要求：

- Python `>=3.11`

## 快速开始

### 统一认证 + 本科教务

```python
from zzupy.app import CASClient, UndergradEASClient

cas = CASClient("your_account", "your_password")
# cas.set_token("your_userToken", "your_refreshToken")
# cas.set_device("your_deviceId")
if cas.mfa.is_required():
    cas.mfa.send_sms()
    cas.mfa.verify_sms(input("input sms code:"))
cas.login()

with UndergradEASClient(cas) as eas:
    eas.login()
    week = eas.get_teaching_week(week=1)
    lesson = week.get(weekday=1, unit=1)
    if lesson:
        print(lesson.course.name_zh)
```

### 校园网 Portal 认证

```python
from zzupy.web import EPortalClient, discover_portal_info

portal = discover_portal_info()
with EPortalClient(portal.portal_server_url, bind_address=portal.user_ip, force_bind=True) as client:
    result = client.auth("your_account", "your_password")
    print(result.message)
```

## 桌面 GUI

安装项目后运行：

```bash
zzu-gui
```

GUI 支持账号密码、可选 `deviceId`、已有 `userToken` / `refreshToken` 复用和短信 MFA。勾选“记住账号”只保存学号；勾选“记住密码并自动登录”后，密码通过 Windows DPAPI 加密再写入 `%APPDATA%\ZZU.Py\settings.json`，密文只能由当前 Windows 用户解密，下次启动会自动登录。Token 不写入配置；学校要求 MFA 时仍需输入短信验证码。

登录后程序自动读取账号绑定的默认寝室及其名称，再扫描同楼栋由服务器实际返回的电表目录；程序优先使用名称含“照明”或“空调”的目录，并按同一寝室名称匹配各自的内部记录 ID。不同目录的编号和末尾 ID 都可以不同，无需假定编号以 `99` 开头。Android 端提供余额查询、阈值预警与充值入口，支付密码仅参与当次请求且不保存。

成绩页按学期分组显示课程成绩，可展开查看接口返回的全部成绩分项，并以四位小数展示总绩点。成绩总表可由本地数据生成；官方排名证明仍依赖教务网页会话，学校统一认证策略变化时可能不可用。排名证明只返回当前账号的官方结果，不会读取或枚举专业内其他同学的成绩。

课表页先加载可用学期，再按教学周查询；同一门课连续占用多节时只显示一行，并列出日期、节次、教师、校区、楼栋和教室。网页与安卓端提供上一周/下一周切换、日期条和适合窄屏查看的当日时间线。“下载 iCalendar”会将当前所选学期的完整课表保存为 `.ics` 文件，可导入系统日历、Outlook 等日历应用。

网络设备页连接校园网自助服务系统，默认地址为 `http://10.2.7.16:8080`，也可按校区实际地址修改。网络账号与统一认证账号可相同，但网络密码只用于本次连接、不写入配置。页面可刷新在线设备，并在选中一台设备且二次确认后将该会话下线；使用时需要能够访问校园内网自助服务地址。

## 命令行工具

安装项目后可直接使用 `zzu` 命令。账号可通过 `--account` 或 `ZZU_ACCOUNT` 提供；统一认证密码使用隐藏输入，不会保存到磁盘。

```bash
# 查询默认寝室剩余电量
zzu --account 你的学号 energy

# 查一次电量，低于阈值（默认 2 度）时发送提醒邮件；适合交给 cron 定时调用
zzu --account 你的学号 energy-check --threshold 2

# 常驻巡检，每 30 分钟一次
zzu --account 你的学号 energy-watch --interval 30

# 查询电量并显示估算的耗电速度
zzu --account 你的学号 energy --rate


# 查询成绩，也可加 --semester 2025 或 --json
zzu --account 你的学号 grades

# 查看培养计划完成情况（从教务读取官方学分要求与计划课程）
zzu --account 你的学号 plan
```

### 耗电速度

每次查到电量都会记一次采样，之后用最小二乘拟合出日均耗电量，估算「还能用几天」。比只看两次读数的差值稳，抄表噪声会被摊平。至少需要 2 个采样点且跨度不少于 6 小时；中途充过值时会提示「期间电量没有下降」而不是给出负速度。

```
照明：12.5 度，日均 0.42 度，约还能用 29 天
空调：8.75 度，日均 2.10 度，约还能用 4.2 天
```

### 培养计划完成情况

学分要求与计划课程直接从本科教务的「培养计划完成情况预览」读取，不需要自己维护配置文件。完成度按计划里的**学分模块**统计（必修课、校/院任选课、限选课等），模块的要求学分与计划课程都来自教务官方数据。

两个实际数据里踩出来的要点：页面把数据以 **JavaScript 对象字面量**内联在 `var model = {...}` 里（单引号、裸键、`$` 开头的键），所以 `json.loads` 解析不了，需要用 `zzupy.web.jsdata` 里只解析数据字面量的解析器；未通过的取值是 `UNREPAIRED`（挂科未重修）而不是 `FAILED`，只匹配 `FAILED` 会一门课都列不出来。完成度**优先采用页面给出的模块汇总**（教务官方口径）。未通过/在修课程会单独列出。详见[培养计划完成情况](https://illustar0.github.io/ZZU.Py/usage/app/plan/)。

### 电量预警与邮件提醒

寝室电量低于阈值（默认 2 度）时，可以同时收到系统通知和提醒邮件。同一个低电量状态只提醒一次，电量回升后自动重新武装；持续低电量超过冷却时间会补发一次，避免长期断电却彻底静默。

发信基于 HTTP 发信 API（[Resend](https://resend.com) 或 [Brevo](https://brevo.com)），只需在你的域名上配置 SPF / DKIM 的 DNS 记录，不需要真实域名邮箱，也不用改 MX 记录。凭据全部通过环境变量提供：

```bash
export ZZU_MAIL_PROVIDER=resend
export ZZU_MAIL_API_KEY=re_xxxxxxxx
export ZZU_MAIL_FROM=alert@example.com
export ZZU_MAIL_TO=me@example.com
export ZZU_ENERGY_THRESHOLD=2
```

安卓端不保存发信密钥：它在本地判断电量后把读数上报给服务端的 `POST /api/energy-alert`，由服务端发信，因此服务端不需要保存任何统一认证凭据。完整说明、接口示例与域名邮箱 DNS 记录见[电量预警与邮件提醒](https://illustar0.github.io/ZZU.Py/usage/app/energy-alert/)。

## 模块概览

### `zzupy.app`

- `CASClient`: App 端统一认证
- `UndergradEASClient`: 新本科教务课表、学期与成绩数据
- `ECardClient`: 校园卡余额、电费与房间相关接口

### `zzupy.web`

- `discover_portal_info`: 自动探测校园网 Portal 参数
- `EPortalClient`: Portal 认证
- `SelfServiceSystem`: 自助服务系统设备管理
- `StudentWebEASClient`: 复用统一认证会话读取最高成绩记录、官方成绩总表与成绩排名证明

### 电量预警

- `zzupy.energy`: 阈值判断、提醒去重状态与提醒邮件文案
- `zzupy.energy_history`: 电量采样历史与耗电速度估算
- `zzupy.mail`: 基于 Resend / Brevo HTTP 发信 API 的邮件发送
- `zzupy.alerting`: 读配置、查电量、判断阈值、发信的编排逻辑

### 学业统计

- `zzupy.plan`: 解析教务培养计划页面（JS 字面量）并统计各学分模块完成度
- `zzupy.web.jsdata`: 只解析数据字面量的 JS 对象解析器（内联数据用）

### `zzupy.aio`

- 提供 `app` 与 `web` 下主要客户端的异步版本

## 网页端

- 生产网站：<https://zzu.ylyg.eu.org>
- 网页端由 `api/`（Vercel 上的 FastAPI 函数）与 `src/`（前端）组成，两者都直接依赖本仓库的 `zzupy/`。
- 服务端负责概率性任务与无需本地凭据的功能：低电量邮件提醒、按房间读取寝室电量等。
- 部署：Vercel 读取 `vercel.json`；`vercel.json` 中的定时任务用于服务端自巡检。

## 安卓客户端

安卓客户端已独立到单独仓库：<https://github.com/zzu-sensei/zzu-life-android>

它不加载或依赖生产网站——登录、成绩、课表、培养计划和寝室电量请求都从手机本地
发往学校接口，内置精简版 ZZU.Py 协议桥接与 Python 3.12 运行时。本仓库不再包含
`flutter-app/` 或任何安卓构建配置。

## 隐私与安全

- 隐私说明：[`PRIVACY.md`](PRIVACY.md)
- 安全问题报告：[`SECURITY.md`](SECURITY.md)
- 贡献指南：[`CONTRIBUTING.md`](CONTRIBUTING.md)
- 第三方组件声明：[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)

## 文档

- 使用文档：<https://illustar0.github.io/ZZU.Py/>
- API 参考：<https://illustar0.github.io/ZZU.Py/reference/api/>
- 文档站点由 `Zensical` 构建

## 开发

项目使用 `uv` 管理环境和命令。

```bash
uv sync --extra develop,docs
uv run python scripts/run_tests.py     # 全部离线自检
uv run python scripts/generate_api_reference.py
uv run zensical serve
uv run zensical build
ruff format zzupy
ruff check zzupy
ty check zzupy
uv build
```

自检是 `scripts/test_*.py` 下的独立脚本（不用 pytest），`run_tests.py` 自动发现并运行，
**不联网、不需要账号**。改动后请确保全绿。需要真实登录的排查脚本放在 `scripts/dev/`。

安卓端与仓库指南见 [`AGENTS.md`](AGENTS.md) 和 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

异常处理建议优先捕获 `zzupy.exception.ZZUError`，再按需细分到 `NetworkError`、`ParsingError`、`OperationError`、`InvalidArgumentError` 等具体异常。

如需快速打开库内日志，推荐直接调用 `logger.enable("zzupy")`。
```python
# 启用 TRACE 日志
from loguru import logger
import sys

logger.remove()
logger.add(sys.stderr, level="TRACE")
logger.enable("zzupy")
```

## 许可证

本项目使用 MIT 许可证，详见 `LICENSE`。

## 相关链接

- GitHub：<https://github.com/zzu-sensei/zzu_my>
- Issues：<https://github.com/zzu-sensei/zzu_my/issues>
- 上游项目：<https://github.com/Illustar0/ZZU.Py>
