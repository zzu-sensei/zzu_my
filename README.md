# ZZU.Py / 郑大生活助手

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-%3E%3D3.11-blue.svg)](pyproject.toml)
[![Flutter](https://img.shields.io/badge/Flutter-3.47.5-54C5F8.svg)](flutter-app/README.md)

豫见郑大相关服务的 Python API 封装、网页端与 Android 客户端。

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


# 查询成绩，也可加 --semester 2025 或 --json
zzu --account 你的学号 grades
```

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

### `zzupy.aio`

- 提供 `app` 与 `web` 下主要客户端的异步版本

## 网页与安卓端

- 生产网站：<https://zzu.ylyg.eu.org>
- `flutter-app/` 是当前 Android 客户端，不加载或依赖生产网站；登录、成绩、课表和寝室电量请求均从手机本地发往学校接口。
- 客户端采用 Flutter 液态玻璃界面；Android 平台通道复用本地 Chaquopy/ZZU.Py、加密会话和桌面小组件。
- 安卓端内置针对移动环境精简的 ZZU.Py 协议桥接与 Python 3.12 运行时，提供本地加密会话、按学期分组的成绩与打印、自动定位当前教学周的周课表、照明/空调双电表识别、电费充值双重确认，以及“今日课表”和“寝室电量”桌面小组件。支付密码仅参与当次本地加密请求，不会保存。
- 当前直装包仅包含主流 `arm64-v8a` 架构，并使用 Android 调试证书签署，仅供侧载测试，不适用于应用商店发布。源码构建说明见 [`flutter-app/README.md`](flutter-app/README.md)。

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
uv run python scripts/generate_api_reference.py
uv run zensical serve
uv run zensical build
ruff format zzupy
ruff check zzupy
ty check zzupy
uv build
```

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
