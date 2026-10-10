# 第三方组件声明

本仓库（Python 库与网页端）依赖以下第三方组件。完整依赖版本见 `uv.lock` 与
`package-lock.json`。

| 组件 | 用途 | 许可证 | 来源 |
| --- | --- | --- | --- |
| ZZU.Py | 学校服务 API 客户端 | MIT | 本仓库及上游 `Illustar0/ZZU.Py` |
| gmalg | 国密算法实现 | MIT | <https://github.com/ww-rm/gmalg> |
| pycparser | C 语法解析，供 CFFI 使用 | BSD-3-Clause | <https://github.com/eliben/pycparser> |

安卓客户端（Flutter、Chaquopy 等）已迁到
<https://github.com/zzu-sensei/zzu-life-android>，其第三方组件声明见该仓库。
