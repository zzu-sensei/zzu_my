# 贡献指南

感谢参与 ZZU.Py / 郑大生活助手。

## 提交前

1. 先搜索现有 Issue，确认问题没有重复。
2. 不要提交真实学号、密码、Token、Cookie、设备标识、宿舍号或含个人信息的抓包数据。
3. 不要绕过学校认证、访问他人数据、批量枚举账号或增加违反学校规定的功能。
4. 修改同步客户端时检查 `zzupy/aio` 的异步实现是否也需要同步。

## 本地检查

Python：

```bash
uv sync --extra develop,docs
uv run python scripts/run_tests.py      # 全部离线自检
uv run python scripts/run_tests.py plan # 只跑名字含 plan 的
uv run ruff check zzupy
uv run ty check zzupy
uv build
```

自检是 `scripts/test_*.py` 下的独立脚本（不用 pytest），`run_tests.py` 会自动发现并
运行。它们**不联网、不需要账号**，改动后请确保全绿再加新功能。

修 bug 时请先让新断言真的失败一次（例如临时改回旧实现），确认测试能抓住问题，
再恢复修复——不会失败的测试没有意义。

需要真实登录的排查脚本放在 `scripts/dev/`，不属于自检范围：

```bash
python scripts/dev/session.py <页面URL>              # 建立会话并抓页面
python scripts/dev/diagnose_plan_page.py <页面文件>   # 离线分析页面结构
```

这些脚本会产生含个人信息与会话凭据的临时文件，**用完请删除，不要提交**。

网页：

```bash
npm ci
npm run build
```

文档用 Zensical 构建（`zensical.toml`）：

```bash
uv run zensical build
```

Android 客户端在**另一个仓库**：<https://github.com/zzu-sensei/zzu-life-android>。
本仓库不再包含 `flutter-app/`，也不接受安卓构建配置或 APK 工作流的改动。

如果你改的是两端共有的规则（培养计划解析、通过判定、绩点算法），请**两个仓库都改**，
并让各自的测试保持同步：本仓库是 `scripts/test_plan_progress.py`，那边是
`scripts/test_mobile_plan.py`。手机端的 `mobile_zzupy.py` / `mobile_plan_page.py` 是
**并行实现**——因为 `zzupy.logging` 依赖 `loguru`，而 `loguru` 没有打包进 App。


## Pull Request

- 每个 PR 聚焦一个问题，说明行为变化、验证方式和可能影响。
- UI 变化请附脱敏截图；接口变化请提供脱敏后的响应结构，不要提供完整响应。
- 新增依赖必须说明用途、许可证和为什么不能使用现有依赖完成。
- 提交即表示你有权贡献相应代码，并同意代码按本仓库 MIT 许可证发布。
