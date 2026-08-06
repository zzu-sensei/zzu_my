# ZZU.Py

[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/Illustar0/ZZU.Py)    

豫见郑大相关服务的 Python API 封装。

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

寝室电费页只提供查询，不包含充值。登录后程序自动读取账号绑定的默认寝室及其名称，再扫描同楼栋由服务器实际返回的电表目录；程序优先使用名称含“照明”或“空调”的目录，并按同一寝室名称匹配各自的内部记录 ID。不同目录的编号和末尾 ID 都可以不同，无需逐级手动选择。

成绩页按学期分组显示课程成绩。当前个人成绩接口不返回班级/专业参照人数与名次，因此无法可靠提供总排名或各学期排名，GUI 会明确标注为接口未提供。

课表页先加载可用学期，再按教学周查询；同一门课连续占用多节时只显示一行，并列出日期、节次、教师、校区、楼栋和教室。“下载 iCalendar”会将当前所选学期的完整课表保存为 `.ics` 文件，可导入系统日历、Outlook 等日历应用。

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

### `zzupy.aio`

- 提供 `app` 与 `web` 下主要客户端的异步版本

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

- GitHub：<https://github.com/Illustar0/ZZU.Py>
- Issues：<https://github.com/Illustar0/ZZU.Py/issues>
