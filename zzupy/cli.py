"""ZZU.Py 的安全命令行入口。"""

from __future__ import annotations

import argparse
from getpass import getpass
import json
import os
import sys
import time

from zzupy.alerting import read_room_readings, run_energy_alert
from zzupy.app import CASClient, ECardClient, UndergradEASClient
from zzupy.energy_history import EnergyHistory, format_drain_line
from zzupy.exception import ZZUError
from zzupy.logging import logger
from zzupy.mail import MailConfigError, MailSendError
from zzupy.plan import PlanParseError, format_completion
from zzupy.web import StudentWebEASClient


def _create_cas(account: str | None) -> CASClient:
    account = account or os.environ.get("ZZU_ACCOUNT") or input("学号: ").strip()
    password = os.environ.get("ZZU_PASSWORD") or getpass("统一认证密码: ")
    cas = CASClient(account, password)
    try:
        if cas.mfa.is_required():
            cas.mfa.send_sms()
            cas.mfa.verify_sms(input("短信验证码: ").strip())
        cas.login()
        return cas
    except BaseException:
        cas.close()
        raise


def _energy(cas: CASClient, room: str | None, show_rate: bool = False) -> None:
    history = EnergyHistory()
    with ECardClient(cas) as ecard:
        ecard.login()
        target = room or ecard.get_default_room()
        remaining = ecard.get_remaining_energy(target)
        print(f"寝室 {target} 剩余电量: {remaining:g}")

    if show_rate:
        estimates = history.estimate()
        if not estimates:
            print("还没有足够的历史采样，多查几次再试（也可用 energy-watch 持续采样）。")
            return
        print("耗电速度估算：")
        for estimate in estimates:
            print(f"  {format_drain_line(estimate)}")


def _energy_check(cas: CASClient, room: str | None, threshold: float | None) -> None:
    """查一次电量并按需发提醒邮件，适合交给 cron / systemd timer 调用。"""
    history = EnergyHistory()
    with ECardClient(cas) as ecard:
        ecard.login()
        target, readings = read_room_readings(ecard, room or "", history=history)

    result = run_energy_alert(readings, room=target, threshold=threshold)
    for item in result.readings:
        if item.ok:
            print(f"  {item.label}: {item.remaining:g} 度")
        else:
            print(f"  {item.label}: 读取失败（{item.error}）")

    # 每次采样都顺带给出耗电速度，数据不够时这行会说明原因。
    for estimate in history.estimate():
        print(f"  {format_drain_line(estimate)}")

    if result.mail is not None:
        print(f"已发送提醒邮件（{result.mail.provider}）")
    elif result.decision.low:
        print(f"电量偏低但未重复发信：{result.decision.reason or '已提醒过'}")
    else:
        print(f"电量正常：{result.decision.reason}")
    print(json.dumps(result.to_dict(), ensure_ascii=False))


def _energy_watch(
    cas: CASClient,
    room: str | None,
    threshold: float | None,
    interval_minutes: int,
    once: bool,
) -> int:
    """常驻巡检：适合在电脑或服务器上长期运行。"""
    interval = max(1, interval_minutes) * 60
    logger.info("开始电量巡检，每 {} 分钟一次", max(1, interval_minutes))
    while True:
        try:
            _energy_check(cas, room, threshold)
        except (ZZUError, MailConfigError, MailSendError, ValueError) as exc:
            # 单次失败不应该让常驻进程退出，否则错过了这次就再也收不到提醒。
            print(f"本次巡检失败: {exc}", file=sys.stderr)
        if once:
            return 0
        time.sleep(interval)


def _plan(cas: CASClient, as_json: bool, program_id: str | None) -> None:
    """查看培养计划完成情况。

    学分要求、计划课程与完成度全部来自教务网页端的「培养计划完成情况预览」，
    因此这里需要网页端登录（用 App 的 userToken 换取网页会话）。页面已经算好了
    各模块的通过／在修／未通过学分，直接采用即可，不再自行统计成绩，避免两套
    口径对不上。
    """
    with StudentWebEASClient(cas) as web:
        web.login()
        plan = web.get_program_plan(program_id)

    if as_json:
        print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
        return

    print(format_completion(plan))


def _grades(cas: CASClient, semester: str | None, as_json: bool) -> None:
    with UndergradEASClient(cas) as eas:
        eas.login()
        grades = eas.get_grades()

    if semester:
        grades = [grade for grade in grades if semester in grade.semester.name_zh]
    if as_json:
        data = [grade.model_dump(mode="json", by_alias=True) for grade in grades]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    if not grades:
        print("没有查询到符合条件的成绩。")
        return

    grouped: dict[str, list] = {}
    for grade in grades:
        grouped.setdefault(grade.semester.name_zh or "未知学期", []).append(grade)

    for semester in sorted(grouped, reverse=True):
        print(f"\n[{semester}]")
        print("课程\t成绩\t绩点\t学分\t状态")
        for grade in grouped[semester]:
            final_grade = grade.final_grade or "未发布"
            gp = "-" if grade.gp is None else f"{grade.gp:g}"
            status = (
                "未知"
                if grade.passed is None
                else "通过" if grade.passed else "未通过"
            )
            print(
                f"{grade.course_name_zh}\t{final_grade}\t{gp}\t"
                f"{grade.credits:g}\t{status}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="郑州大学生活与教务服务命令行工具")
    parser.add_argument("--account", help="学号；也可设置 ZZU_ACCOUNT")
    subparsers = parser.add_subparsers(dest="command", required=True)

    energy = subparsers.add_parser("energy", help="查询寝室剩余电量")
    energy.add_argument("--room", help="寝室 ID；不传则查询默认寝室")
    energy.add_argument(
        "--rate",
        action="store_true",
        help="同时显示根据历史采样估算的耗电速度",
    )

    check = subparsers.add_parser(
        "energy-check",
        help="查一次电量，低于阈值时发提醒邮件（适合 cron 定时调用）",
    )
    check.add_argument("--room", help="寝室 ID；不传则查询默认寝室")
    check.add_argument(
        "--threshold",
        type=float,
        help="预警阈值（度）；默认读 ZZU_ENERGY_THRESHOLD，未设置时为 2",
    )

    watch = subparsers.add_parser(
        "energy-watch",
        help="常驻巡检电量，低于阈值时发提醒邮件",
    )
    watch.add_argument("--room", help="寝室 ID；不传则查询默认寝室")
    watch.add_argument(
        "--threshold",
        type=float,
        help="预警阈值（度）；默认读 ZZU_ENERGY_THRESHOLD，未设置时为 2",
    )
    watch.add_argument(
        "--interval",
        type=int,
        default=30,
        help="巡检间隔（分钟），默认 30",
    )
    watch.add_argument(
        "--once",
        action="store_true",
        help="只巡检一次就退出",
    )

    grades = subparsers.add_parser("grades", help="查询全部已发布成绩")
    grades.add_argument("--semester", help="按学期名称包含关系筛选")
    grades.add_argument("--json", action="store_true", help="输出 JSON")

    plan = subparsers.add_parser(
        "plan",
        help="查看培养计划完成情况（从教务读取官方学分要求与计划课程）",
    )
    plan.add_argument("--json", action="store_true", help="输出 JSON")
    plan.add_argument(
        "--program-id",
        help="培养计划 ID；不传时由教务跳转到当前学生的计划",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()

    cas: CASClient | None = None
    try:
        cas = _create_cas(args.account)
        if args.command == "energy":
            _energy(cas, args.room, args.rate)
        elif args.command == "energy-check":
            _energy_check(cas, args.room, args.threshold)
        elif args.command == "energy-watch":
            return _energy_watch(
                cas, args.room, args.threshold, args.interval, args.once
            )
        elif args.command == "plan":
            _plan(cas, args.json, args.program_id)
        else:
            _grades(cas, args.semester, args.json)
        return 0
    except (ZZUError, MailConfigError, MailSendError, PlanParseError, ValueError) as exc:
        print(f"操作失败: {exc}", file=sys.stderr)
        # ZZUError 会带结构化上下文，把关键诊断信息一并打印，否则用户只能看到
        # 一句「解析失败」，无法判断是登录态问题还是接口形态变了。
        context = getattr(exc, "context", None)
        if context:
            for key in ("url", "status", "content_type", "length", "hint", "preview"):
                if key in context:
                    print(f"  {key}: {context[key]}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n操作已取消。", file=sys.stderr)
        return 130
    finally:
        if cas is not None:
            cas.close()


if __name__ == "__main__":
    raise SystemExit(main())