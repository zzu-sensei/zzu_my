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
uv run ruff check zzupy
uv run ty check zzupy
uv build
```

网页：

```bash
npm ci
npm run build
```

Android：

```bash
cd flutter-app
flutter pub get
flutter analyze
flutter build apk --release --target-platform android-arm64
```

Android 构建需要 JDK 17、Android SDK 35 和 Python 3.12。若 Python 不在 `PATH`，可在本机设置 `CHAQUOPY_BUILD_PYTHON`，不要把本机绝对路径提交到仓库。

## Pull Request

- 每个 PR 聚焦一个问题，说明行为变化、验证方式和可能影响。
- UI 变化请附脱敏截图；接口变化请提供脱敏后的响应结构，不要提供完整响应。
- 新增依赖必须说明用途、许可证和为什么不能使用现有依赖完成。
- 提交即表示你有权贡献相应代码，并同意代码按本仓库 MIT 许可证发布。
