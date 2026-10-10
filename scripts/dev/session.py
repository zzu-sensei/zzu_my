"""建立并缓存教务会话（Token 复用，避免每次都要 MFA）。

这是**联网开发工具**，不在 ``scripts/test_*.py`` 的自检范围内（自检必须离线可跑）。

会话缓存默认写到 ``%TEMP%/zzu-dev-session.json``（仓库外）。缓存含 token、密码与
个人信息，分析完请删除。首次需要 MFA：脚本会下发短信，然后把验证码写进
``<临时目录>/zzu-dev-mfa.txt``，它会自动等待（最多 15 分钟）。

用法：
    python scripts/dev/session.py                     # 建立/复用会话
    python scripts/dev/session.py <URL>               # 抓取页面并落盘
    python scripts/dev/session.py <URL> --out DIR     # 指定落盘目录

环境变量：
    ZZU_TEST_ACCOUNT / ZZU_TEST_PASSWORD   账号密码（缓存里也会记住）
    ZZU_DEV_SESSION                        会话缓存路径
    ZZU_DEV_MFA                            验证码文件路径
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from zzupy.app import CASClient
from zzupy.exception import MFAError, ZZUError
from zzupy.web import StudentWebEASClient

_TEMP = Path(tempfile.gettempdir())
CACHE = Path(os.environ.get("ZZU_DEV_SESSION") or (_TEMP / "zzu-dev-session.json"))
MFA_FILE = Path(os.environ.get("ZZU_DEV_MFA") or (_TEMP / "zzu-dev-mfa.txt"))
OUT_DIR = _TEMP / "zzu-dev-pages"



def load_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def save_cache(data: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  会话已缓存到 {CACHE}")


def read_code() -> str:
    raw = MFA_FILE.read_text(encoding="utf-8-sig")
    return "".join(ch for ch in raw if ch.isdigit())


def build_client() -> CASClient:
    cache = load_cache()
    account = os.environ.get("ZZU_TEST_ACCOUNT") or cache.get("account", "")
    password = os.environ.get("ZZU_TEST_PASSWORD") or cache.get("password", "")
    if not account:
        raise SystemExit("缺少账号：设置 ZZU_TEST_ACCOUNT 或先建立缓存")

    cas = CASClient(account, password)
    cas.set_device("ZZU.Py diagnostics")

    token = cache.get("user_token")
    refresh = cache.get("refresh_token")
    if token and refresh:
        print("  发现缓存 token，尝试复用（可跳过 MFA）")
        cas.set_token(token, refresh)
        # MFA 状态必须一并恢复，否则 login() 会判「MFA 状态错误」。
        cas.mfa.state = cache.get("mfa_state") or "verified-token-session"
        cas.mfa.required = bool(cache.get("mfa_required", False))
        cas.mfa.verified = bool(cache.get("mfa_verified", True))
        try:
            cas.login()
            print("  token 复用成功")
            return cas
        except (ZZUError, MFAError) as exc:
            print(f"  token 失效：{exc}，改为账密登录")
            cas.mfa.state = ""
            cas.mfa.required = False
            cas.mfa.verified = False

    if cas.mfa.is_required():
        print("  需要 MFA，发送短信…")
        sent = False
        for attempt in range(1, 16):
            try:
                cas.mfa.send_sms()
                sent = True
                print(f"  第 {attempt} 次尝试：短信已下发")
                break
            except ZZUError as exc:
                print(f"  第 {attempt} 次：{exc}；60s 后重试")
                time.sleep(60)
        if not sent:
            raise SystemExit("无法下发验证码")
        MFA_FILE.unlink(missing_ok=True)
        print(f"\n>>> 请把验证码写入 {MFA_FILE} <<<\n")
        deadline = time.time() + 900
        while time.time() < deadline and not MFA_FILE.exists():
            time.sleep(3)
        code = read_code()
        if not code:
            raise SystemExit("等待验证码超时")
        print(f"  使用验证码 {code}")
        cas.mfa.verify_sms(code)

    cas.login()
    print("  登录成功")
    save_cache(
        {
            "account": account,
            "password": password,
            "user_token": cas.user_token,
            "refresh_token": cas.refresh_token,
            "mfa_state": cas.mfa.state,
            "mfa_required": cas.mfa.required,
            "mfa_verified": cas.mfa.verified,
        }
    )
    return cas


def main() -> None:
    parser = argparse.ArgumentParser(description="建立教务会话并可选抓取页面")
    parser.add_argument("url", nargs="?", help="要抓取的完整 URL")
    parser.add_argument("--out", help=f"落盘目录（默认 {OUT_DIR}）")
    args = parser.parse_args()

    cas = build_client()
    with StudentWebEASClient(cas) as web:
        web.login()
        print(f"  网页会话建立，学生内部 ID: {web.student_id}")
        save_cache({**load_cache(), "student_id": web.student_id})

        if args.url:
            out_dir = Path(args.out) if args.out else OUT_DIR
            out_dir.mkdir(parents=True, exist_ok=True)
            response = web._get_url(args.url)
            name = re.sub(r"[^A-Za-z0-9_.-]", "_", args.url.split("/student/")[-1])
            target = out_dir / f"{(name or 'page')[:80]}.html"
            target.write_text(response.text, encoding="utf-8")
            print(f"  {response.status_code}  {len(response.text)} 字符 -> {target}")
            print(f"  离线分析: python scripts/dev/diagnose_plan_page.py {target}")
    cas.close()

    if CACHE.exists():
        print(f"\n  提示：会话缓存 {CACHE} 含凭据，用完请删除。")


if __name__ == "__main__":
    main()
