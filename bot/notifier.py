"""对外文案生成（发布大厅卡片、抢单话术、结果通知等）。"""
from __future__ import annotations

from typing import Any

from .config import get_designers, get_source_groups
from .models import Order, status_label


def _amount(o: Order) -> str:
    return f"{o.amount:g}" if o.amount is not None else "?"


def order_card(o: Order) -> str:
    """发布到抢单大厅的新单卡片。"""
    t = o.otype or "未分类"
    return (
        f"【新单 #{o.id}｜{t}】\n"
        f"  类型: {t}   页数: {o.pages if o.pages is not None else '?'} 页"
        f"   金额: {_amount(o)} 元\n"
        f"  备注: {o.note if o.note else '(无)'}\n"
        f"  来源: {o.source_group_name}\n"
        f"  原文: {o.raw[:80]}\n"
        f"  >> 想接的回复: 抢 #{o.id}"
    )


def status_card(o: Order) -> str:
    s = o.designer_name or "?"
    return f"订单 #{o.id} [{status_label(o.status)}] 设计: {s}"


def claim_phrase(cfg: dict[str, Any], o: Order, mode: str) -> str:
    """生成发往企微侧的抢单话术。"""
    claim = cfg.get("claim", {})
    if mode == "private":
        tmpl = claim.get("phrase_private", "老板，{type} {pages}页 金额{amount}元 我来接")
    else:
        tmpl = claim.get("phrase_group", "扣1，接单：{type} {pages}页 金额{amount}元")
    pages = o.pages if o.pages is not None else ""
    return tmpl.format(type=o.otype or "单", pages=pages, amount=_amount(o))


def grabbed_locked(o: Order) -> str:
    return f"已锁定 #{o.id}（{status_label(o.status)}）。机器人将前往企微侧抢单，结果稍后通知。"


def queued(o: Order, pos: int) -> str:
    return (
        f"你已抢 #{o.id}，但同群还有更早的抢单在执行，机器人已把你排在第 {pos} 位，"
        f"上一单结果出来后会自动去抢。"
    )


def claim_sent(o: Order, mode: str) -> str:
    where = "企微上家群发送抢单话术" if mode == "group" else "私聊企微上家"
    return f"机器人正在{where}（订单 #{o.id}），等待对方确认抢单结果…"


def won(o: Order) -> str:
    return (
        f"恭喜！订单 #{o.id}（{o.otype or ''} {o.pages if o.pages is not None else '?'}页 "
        f"金额{_amount(o)}元）抢单成功。\n"
        f"派单员将拉群对接，请留意群通知。"
    )


def lost(o: Order) -> str:
    return (
        f"很遗憾，订单 #{o.id}（{o.otype or ''} 金额{_amount(o)}元）已被其他店铺接走。\n"
        f"你可以去大厅抢其他单：回复 大厅 查看待抢列表。"
    )


def manual_notice(o: Order) -> str:
    return (
        f"订单 #{o.id} 机器人抢单后迟迟无法自动判定结果，需要人工确认。\n"
        f"请查看企微来源群（{o.source_group_name}），然后回复：确认 #{o.id} 成功 / 确认 #{o.id} 失败"
    )


def manual_claim_needed(o: Order) -> str:
    """来源群机器人无法自动发言(微信大群/别人企微群)：派单员需亲自去群里抢。"""
    return (
        f"订单 #{o.id} 需要人工去来源群抢单（机器人无法在该群自动发言）。\n"
        f"  类型: {o.otype or ''}  {o.pages if o.pages is not None else '?'}页  "
        f"金额{_amount(o)}元\n"
        f"  来源群: {o.source_group_name}\n"
        f"  原文: {o.raw[:80]}\n"
        f"请去该群发送抢单话术（扣1/私聊上家），完成后回复：确认 #{o.id} 成功 / 确认 #{o.id} 失败"
    )


def hall_pending_list(orders: list[Order]) -> str:
    if not orders:
        return "当前没有待抢订单。"
    lines = []
    for o in orders:
        lines.append(
            f"- #{o.id} {o.otype or '未分类'} {o.pages if o.pages is not None else '?'}页 "
            f"金额{_amount(o)}元 | {o.note[:20] if o.note else '无备注'}"
        )
    return "当前待抢订单:\n" + "\n".join(lines)


def help_text() -> str:
    return (
        "指令说明:\n"
        "  抢 #单号        -> 抢指定订单\n"
        "  抢              -> 只有一个待抢单时直接抢\n"
        "  大厅 / 列表     -> 查看当前待抢订单\n"
        "  (派单员) 确认 #单号 成功/失败 -> 人工确认抢单结果"
    )


def dispatcher_won_notice(cfg: dict[str, Any], o: Order) -> str:
    return (
        f"订单 #{o.id} 已抢到！请拉群对接。\n"
        f"  设计: {o.designer_name}\n"
        f"  类型: {o.otype or ''}  {o.pages if o.pages is not None else '?'}页  金额{_amount(o)}元\n"
        f"  来源企微群: {o.source_group_name}\n"
        f"  原文: {o.raw[:80]}"
    )


def resolve_ok(o: Order) -> str:
    return f"订单 #{o.id} 已人工确认 -> {status_label(o.status)}。"


def not_grabable(o: Order) -> str:
    return f"订单 #{o.id} 当前状态为 {status_label(o.status)}，无法抢单。"


def clarify() -> str:
    return "有多笔待抢订单，请指明单号，例如：抢 #3"


def own_order_taken() -> str:
    return "该订单已被抢，试试其他单，或回复 大厅 查看列表。"


def designer_map_text(cfg: dict[str, Any]) -> str:
    ds = get_designers(cfg)
    return "、".join(f"{v.get('name')}" for v in ds.values()) or "(未配置设计师)"
