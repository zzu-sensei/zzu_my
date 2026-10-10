"""运行 scripts/ 下所有离线自检。

这些自检不联网、不需要账号，覆盖电量预警、耗电估算、培养计划解析、HTTP 日志
脱敏等逻辑。改动任何相关代码后都应该先跑这个。

    uv run python scripts/run_tests.py
    .venv\\Scripts\\python.exe scripts\\run_tests.py

    # 只跑名字匹配的
    ... scripts/run_tests.py plan
    # 显示每个用例的输出
    ... scripts/run_tests.py --verbose
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PATTERN_PREFIX = "test_"


def discover(keyword: str | None = None) -> list[Path]:
    """按文件名收集自检脚本。"""
    found = sorted(
        path
        for path in SCRIPTS_DIR.glob(f"{PATTERN_PREFIX}*.py")
        if path.is_file()
    )
    if keyword:
        found = [path for path in found if keyword.lower() in path.stem.lower()]
    return found


def run(path: Path, *, verbose: bool) -> tuple[bool, float, str]:
    """运行一个自检脚本，返回 (是否成功, 耗时秒, 输出)。"""
    started = time.perf_counter()
    completed = subprocess.run(
        [sys.executable, str(path)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    elapsed = time.perf_counter() - started
    output = (completed.stdout or "") + (completed.stderr or "")
    if verbose:
        print(output.rstrip())
    return completed.returncode == 0, elapsed, output


def main() -> int:
    parser = argparse.ArgumentParser(description="运行所有离线自检")
    parser.add_argument("keyword", nargs="?", help="只跑文件名包含该关键词的自检")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示完整输出")
    args = parser.parse_args()

    cases = discover(args.keyword)
    if not cases:
        print(f"没有找到匹配的自检（关键词：{args.keyword!r}）")
        return 1

    print(f"共 {len(cases)} 个自检\n")
    failures: list[tuple[str, str]] = []
    total = 0.0

    for case in cases:
        ok, elapsed, output = run(case, verbose=args.verbose)
        total += elapsed
        mark = "通过" if ok else "失败"
        print(f"  [{mark}] {case.name:<36} {elapsed:5.2f}s")
        if not ok:
            failures.append((case.name, output))

    print()
    if failures:
        print("=" * 72)
        for name, output in failures:
            print(f"\n### {name} 的输出\n")
            print(output.rstrip())
        print("\n" + "=" * 72)

    passed = len(cases) - len(failures)
    print(f"结果：{passed}/{len(cases)} 通过，总耗时 {total:.2f}s")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
