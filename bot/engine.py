"""核心引擎：把两侧消息转成业务动作，维护订单状态机。

流程:
  企微上家群新单 -> PENDING(发布大厅) -> 设计师抢 -> CLAIMING(锁定,机器人去企微侧抢单)
  -> 企微确认消息判定 -> WON(通知设计师+派单员) / LOST(通知设计师) / 超时 -> MANUAL(派单员人工确认)

同源群串行：同一上家群同时只执行一个抢单，后续抢单自动排队（可配置关闭）。
"""
from __future__ import annotations

import re
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

from . import notifier
from .config import (
    get_designers,
    get_dispatcher,
    get_hall,
    get_source_groups,
    designer_name,
)
from .interpreter import Interpreter
from .models import (
    CLAIM_MODE_GROUP,
    CLAIM_MODE_MANUAL,
    CLAIM_MODE_PRIVATE,
    STATUS_CLAIMING,
    STATUS_LOST,
    STATUS_MANUAL,
    STATUS_PENDING,
    STATUS_WON,
    Inbound,
    Order,
    status_label,
)
from .store import Store
from .transport import Transport

_CONFIRM_RE = re.compile(r"确认\s*[#＃号]?\s*(\d+)\s*(成功|失败|抢到|没抢到|已接|没接)")
_LIST_WORDS = ("大厅", "列表", "待抢", "有什么单", "看看单")
_HELP_WORDS = ("帮助", "指令", "菜单", "help", "?")


def _norm(text: str) -> str:
    t = re.sub(r"@所有人|@all|\s+", "", text)
    return t.strip()


class Engine:
    def __init__(
        self,
        cfg: dict[str, Any],
        store: Store,
        interpreter: Interpreter,
        transports: dict[str, Transport],
        clock: Optional[Callable[[], float]] = None,
    ):
        self.cfg = cfg
        self.store = store
        self.interp = interpreter
        self.transports = transports          # {'source': ..., 'ops': ...}
        self._clock = clock or time.time

        # 上家群 -> 该群待抢单队列（串行抢单）
        self._group_queue: dict[str, deque[int]] = {}

        # 各上家群最近消息（供判定上下文）
        self._recent: dict[str, list[str]] = {}

        # 内存缓存 pending/claiming 以便快速判定
        self._cache: dict[int, Order] = {}

        self.source_groups = get_source_groups(cfg)
        self.hall = get_hall(cfg)
        self.designers = get_designers(cfg)
        self.dispatcher = get_dispatcher(cfg)
        self._lock = threading.RLock()   # 供多线程(Web服务)并发访问
        self._load_cache()

    # ---------------- 基础设施 ----------------
    def _load_cache(self) -> None:
        for o in self.store.list_all():
            self._cache[o.id] = o

    def source_transport(self) -> Transport:
        return self.transports["source"]

    def ops_transport(self) -> Transport:
        return self.transports["ops"]

    def send_source(self, peer: str, text: str) -> None:
        self.source_transport().send_text(peer, text)

    def send_ops(self, peer: str, text: str) -> None:
        self.ops_transport().send_text(peer, text)

    def _designer_grab(self, msg: Inbound, order_id: int) -> None:
        ok, text = self.claim_order(
            order_id,
            designer_id=msg.sender,
            designer_name=msg.sender_name or designer_name(self.cfg, msg.sender),
        )
        self.send_ops(msg.sender if not msg.is_group else msg.peer, text)

    # ---------------- 公共抢单入口（群消息 / 网页共用） ----------------
    def claim_order(self, order_id: int, designer_id: str,
                    designer_name: Optional[str] = None) -> tuple[bool, str]:
        """设计师抢单。PENDING -> 锁给该设计师并触发机器人抢单动作。
        返回 (是否成功, 对设计师的提示文案)。多线程安全。"""
        with self._lock:
            o = self._cache.get(order_id)
            if o is None:
                return False, f"没有找到 #{order_id} 这个单。"
            if o.status != STATUS_PENDING:
                if o.designer == designer_id:
                    return False, notifier.not_grabable(o)
                return False, notifier.own_order_taken()

            o.designer = designer_id
            o.designer_name = designer_name or designer_name(self.cfg, designer_id) or designer_id
            o.status = STATUS_CLAIMING
            o.claim_mode = self.claim_mode_for(o.source_group)
            mode = o.claim_mode
            self._cache_save(o)
            self.store.update(order_id, designer=o.designer, designer_name=o.designer_name,
                              status=o.status, claim_mode=o.claim_mode)
            print(f"[引擎] 设计师 {o.designer_name} 抢单 #{o.id}，状态 -> CLAIMING")
            self._enqueue_or_claim(o)
            if mode == CLAIM_MODE_MANUAL:
                # 真正落定状态在 _manual_claim_needed 中已是 MANUAL，取最新状态措辞
                return True, (f"已锁定 #{o.id}。该来源群机器人无法自动发言，"
                              f"派单员将人工去群内抢单，结果出来后通知你。")
            return True, notifier.grabbed_locked(o)

    def claim_mode_for(self, group_id: str) -> str:
        override = self.cfg.get("claim", {}).get("mode_override", "")
        if override:
            return override
        g = self.source_groups.get(group_id, {})
        return g.get("claim_mode", CLAIM_MODE_GROUP)

    def group_name(self, group_id: str) -> str:
        return self.source_groups.get(group_id, {}).get("name", group_id)

    def _cache_save(self, o: Order) -> None:
        self._cache[o.id] = o

    # ---------------- 消息入口 ----------------
    def on_inbound(self, msg: Inbound) -> None:
        with self._lock:
            if msg.world == "source":
                self._on_source(msg)
            elif msg.world == "ops":
                self._on_ops(msg)
            self._tick()

    # ---------------- 企微侧 ----------------
    def _on_source(self, msg: Inbound) -> None:
        # 私聊：仅处理上家（用于 private 抢单确认 / 私发订单）
        is_group_peer = msg.is_group and msg.peer in self.source_groups
        is_owner_private = (not msg.is_group) and any(
            g.get("owner") == msg.sender for g in self.source_groups.values()
        )
        if not (is_group_peer or is_owner_private):
            return

        key = msg.peer if is_group_peer else f"private:{msg.sender}"
        self._recent.setdefault(key, []).append(msg.text)
        self._recent[key] = self._recent[key][-20:]

        if is_group_peer:
            group = msg.peer
            # 1) 该群若有正在执行(已发送话术)的抢单 -> 先判定结果
            active = self._active_claim_for_group(group)
            if active is not None:
                v = self.interp.verdict(
                    msg.text, active,
                    phrase=self._sent_phrase(active),
                    recent=self._recent[key],
                )
                if v.win or v.lose:
                    self._finalize(active, win=v.win, reason=v.reason, by="auto")
                    return
        elif is_owner_private:
            # 私聊上家：若有该上家的 private 抢单在途 -> 判定结果
            active = self._active_claim_for_owner(msg.sender)
            if active is not None:
                v = self.interp.verdict(
                    msg.text, active,
                    phrase=self._sent_phrase(active),
                    recent=self._recent[key],
                )
                if v.win or v.lose:
                    self._finalize(active, win=v.win, reason=v.reason, by="auto")
                    return

        # 2) 否则当作潜在新订单解析
        self._maybe_new_order(msg, group_id=(msg.peer if is_group_peer else None))

    def _maybe_new_order(self, msg: Inbound, group_id: Optional[str]) -> None:
        sender_name = msg.sender_name or msg.sender
        recent = self._recent.get(msg.peer) if msg.peer else None
        if not group_id:
            # 私聊发单：需要找到所属上家群归属（按其 owner 匹配）
            for gid, g in self.source_groups.items():
                if g.get("owner") == msg.sender:
                    group_id = gid
                    break
        self._create_order_from_text(msg.text, group_id, msg.sender, sender_name,
                                     ts=msg.ts, recent=recent or [])

    def ingest_source_text(self, text: str, group_id: str, sender: str = "web",
                           sender_name: str = "派单员") -> tuple[bool, str, Optional[int]]:
        """网页/接口发单入口：粘贴上家群原文 -> AI解析 -> 入厅。返回 (ok, 提示, 订单id)。"""
        if group_id not in self.source_groups:
            return False, f"未配置来源群: {group_id}", None
        with self._lock:
            o = self._create_order_from_text(text, group_id, sender, sender_name)
            if o is None:
                return False, "未能从文本中解析出订单（可能缺少页数/金额特征或与近期重复）。", None
            return True, f"订单已发布 #{o.id}", o.id

    def _create_order_from_text(self, text: str, group_id: Optional[str], sender: str,
                                sender_name: str, ts: Optional[float] = None,
                                recent: Optional[list[str]] = None) -> Optional[Order]:
        """AI 解析并创建订单（含去重）。成功返回 Order，失败/重复返回 None。"""
        group_name = self.group_name(group_id) if group_id else "未知群"
        ana = self.interp.analyze_source(
            text, group_name=group_name,
            sender_name=sender_name, recent=recent or [],
        )
        if not ana.is_order:
            return None
        if group_id is None:
            return None  # 无归属群则忽略

        # 去重：同一群 N 分钟内同文案不重复发布
        dup_win = float(self.cfg.get("order", {}).get("dedupe_minutes", 10))
        if _norm(text) in {_norm(r) for r in self.store.recent_raw(group_id, dup_win)}:
            print(f"[引擎] 忽略重复订单消息（{group_name}）")
            return None

        now = ts if ts is not None else self._clock()
        o = Order(
            source_group=group_id,
            source_group_name=group_name,
            source_sender=sender,
            source_sender_name=sender_name,
            raw=text,
            otype=ana.otype,
            pages=ana.pages,
            amount=ana.amount,
            note=ana.note,
            status=STATUS_PENDING,
            created_at=now,
        )
        o.id = self.store.add_order(o)
        o.created_at = now
        self._cache_save(o)
        print(f"[引擎] 识别新订单 #{o.id}（{group_name}）: {o.otype or '?'} "
              f"{o.pages if o.pages is not None else '?'}页 {o.amount if o.amount is not None else '?'}元")

        if self.cfg.get("order", {}).get("publish_to_hall", True) and self.hall:
            self.send_ops(self.hall.get("id"), notifier.order_card(o))
        return o

    # ---------------- 个人微信侧 ----------------
    def _on_ops(self, msg: Inbound) -> None:
        is_designer = msg.sender in self.designers
        is_dispatcher = msg.sender == self.dispatcher.get("id")
        if not (is_designer or is_dispatcher):
            return

        text = msg.text.strip()

        # 派单员人工确认
        if is_dispatcher:
            m = _CONFIRM_RE.search(text)
            if m:
                oid, verdict = int(m.group(1)), m.group(2)
                win = verdict in ("成功", "抢到", "已接")
                ok, msg = self._manual_resolve(oid, win, by=msg.sender_name, reply_peer=msg.sender)
                return

        # 通用查询/帮助
        if any(w in text for w in _LIST_WORDS):
            pending = [o for o in self._cache.values()
                       if o.status == STATUS_PENDING]
            self.send_ops(msg.sender if not msg.is_group else msg.peer,
                          notifier.hall_pending_list(pending))
            return
        if any(text == w or text.startswith(w) for w in _HELP_WORDS):
            self.send_ops(msg.sender if not msg.is_group else msg.peer,
                          notifier.help_text())
            return

        # 设计师抢单
        if is_designer:
            pending = [o for o in self._cache.values() if o.status == STATUS_PENDING]
            ga = self.interp.analyze_grab(
                text, pending,
                channel="大厅群" if msg.is_group else "私聊",
                sender_name=msg.sender_name,
            )
            if ga.grabbed and ga.order_id is not None:
                self._designer_grab(msg, ga.order_id)
            elif ga.needs_clarify:
                self.send_ops(msg.sender if not msg.is_group else msg.peer,
                              notifier.clarify() + "\n" + notifier.hall_pending_list(pending))
            # 其余闲聊忽略

    # ---------------- 抢单执行与队列 ----------------
    def _enqueue_or_claim(self, o: Order) -> None:
        g = o.source_group
        mode = o.claim_mode or self.claim_mode_for(g)
        if mode == CLAIM_MODE_MANUAL:
            # 来源群是机器人无法自动发言的群(如个人微信大群/别人企微群) -> 转派单员人工抢
            self._manual_claim_needed(o)
            return
        q = self._group_queue.setdefault(g, deque())
        active = self._active_claim_for_group(g)
        if active is not None:
            q.append(o.id)
            pos = len(q)
            o.queue_pos = pos
            self.store.update(o.id, queue_pos=pos)
            print(f"[引擎] 同群已有抢单在途，订单 #{o.id} 排队（第{pos}位）")
            if o.designer:
                self.send_ops(o.designer, notifier.queued(o, pos))
            return
        self._fire_claim(o)

    def _manual_claim_needed(self, o: Order) -> None:
        o.status = STATUS_MANUAL
        o.result_reason = "来源群机器人无法自动发言，需派单员人工去群内抢单"
        o.claim_sent_at = None
        self._cache_save(o)
        self.store.update(o.id, status=o.status, result_reason=o.result_reason)
        print(f"[引擎] 订单 #{o.id} 来源群需人工抢单 -> MANUAL")
        if self.dispatcher:
            self.send_ops(self.dispatcher.get("id"), notifier.manual_claim_needed(o))
        if o.designer:
            self.send_ops(o.designer,
                          f"你已抢 #{o.id}。来源群机器人无法自动发言，派单员将人工去群内抢单，请稍候结果。")
        if self.hall:
            self.send_ops(self.hall.get("id"), notifier.status_card(o))

    def _fire_claim(self, o: Order) -> None:
        mode = o.claim_mode or self.claim_mode_for(o.source_group)
        phrase = notifier.claim_phrase(self.cfg, o, mode)
        now = self._clock()

        if mode == CLAIM_MODE_PRIVATE:
            target = o.source_sender
            if not target:
                g = self.source_groups.get(o.source_group, {})
                target = g.get("owner")
            if target:
                self.send_source(target, phrase)
        else:  # group
            self.send_source(o.source_group, phrase)

        o.claim_sent_at = now
        timeout = float(self.cfg.get("claim", {}).get("timeout_sec", 90))
        o.claim_deadline = now + timeout
        self.store.update(o.id, claim_sent_at=o.claim_sent_at,
                          claim_deadline=o.claim_deadline)
        print(f"[引擎] 已对订单 #{o.id} 发出抢单话术（{mode}模式），等待确认…")
        if o.designer:
            self.send_ops(o.designer, notifier.claim_sent(o, mode))
        if self.hall:
            self.send_ops(self.hall.get("id"), notifier.status_card(o))

    def _active_claim_for_group(self, group: str) -> Optional[Order]:
        for o in self._cache.values():
            if (o.source_group == group and o.status == STATUS_CLAIMING
                    and o.claim_sent_at is not None):
                return o
        return None

    def _active_claim_for_owner(self, owner: str) -> Optional[Order]:
        for o in self._cache.values():
            if (o.status == STATUS_CLAIMING and o.claim_sent_at is not None
                    and o.source_sender == owner
                    and (o.claim_mode or CLAIM_MODE_PRIVATE) == CLAIM_MODE_PRIVATE):
                return o
        return None

    def _sent_phrase(self, o: Order) -> str:
        return notifier.claim_phrase(self.cfg, o, o.claim_mode or CLAIM_MODE_GROUP)

    # ---------------- 结果落定 ----------------
    def _finalize(self, o: Order, win: Optional[bool], reason: str, by: str) -> None:
        if win is True:
            o.status = STATUS_WON
        elif win is False:
            o.status = STATUS_LOST
        else:
            o.status = STATUS_MANUAL
        o.result_reason = f"{reason} (by {by})"
        self._cache_save(o)
        self.store.update(o.id, status=o.status, result_reason=o.result_reason)

        if o.status == STATUS_WON:
            print(f"[引擎] 订单 #{o.id} 抢单成功（{o.source_group_name}）")
            if o.designer:
                self.send_ops(o.designer, notifier.won(o))
            if self.dispatcher:
                self.send_ops(self.dispatcher.get("id"),
                              notifier.dispatcher_won_notice(self.cfg, o))
            if self.hall:
                self.send_ops(self.hall.get("id"), notifier.status_card(o))
        elif o.status == STATUS_LOST:
            print(f"[引擎] 订单 #{o.id} 抢单失败: {reason}")
            if o.designer:
                self.send_ops(o.designer, notifier.lost(o))
            if self.hall:
                self.send_ops(self.hall.get("id"), notifier.status_card(o))
        else:  # MANUAL
            print(f"[引擎] 订单 #{o.id} 进入人工确认: {reason}")
            if self.dispatcher:
                self.send_ops(self.dispatcher.get("id"), notifier.manual_notice(o))
            if o.designer:
                self.send_ops(o.designer,
                              f"订单 #{o.id} 抢单结果暂时无法自动判定，派单员正在人工核对，请稍候。")

        # 释放同群队列：继续下一单
        self._dequeue(o.source_group)

    def _manual_resolve(self, order_id: int, win: bool, by: str, reply_peer: Optional[str]) -> tuple[bool, str]:
        o = self._cache.get(order_id)
        if o is None:
            msg = f"没有订单 #{order_id}。"
            if reply_peer:
                self.send_ops(reply_peer, msg)
            return False, msg
        if o.status in (STATUS_MANUAL, STATUS_CLAIMING):
            self._finalize(o, win=win, reason=f"派单员人工确认={'成功' if win else '失败'}", by=by)
            msg = notifier.resolve_ok(o)
            if reply_peer:
                self.send_ops(reply_peer, msg)
            return True, msg
        msg = f"订单 #{order_id} 当前状态 {status_label(o.status)}，无需人工确认。"
        if reply_peer:
            self.send_ops(reply_peer, msg)
        return False, msg

    def resolve_manual(self, order_id: int, win: bool, by: str = "网页") -> tuple[bool, str]:
        """网页/派单员人工确认接口。"""
        with self._lock:
            return self._manual_resolve(order_id, win, by, reply_peer=None)

    def _dequeue(self, group: str) -> None:
        q = self._group_queue.get(group)
        if not q:
            return
        nid = q.popleft()
        o = self._cache.get(nid)
        if o is not None and o.status == STATUS_CLAIMING and o.claim_sent_at is None:
            o.queue_pos = 0
            self.store.update(o.id, queue_pos=0)
            print(f"[引擎] 开始处理排队订单 #{o.id}")
            self._fire_claim(o)
        elif o is not None:
            # 该单已不是排队态，继续取下一个
            self._dequeue(group)

    # ---------------- 超时 ----------------
    def _tick(self, now: Optional[float] = None) -> None:
        now = now or self._clock()
        for o in list(self._cache.values()):
            if (o.status == STATUS_CLAIMING and o.claim_sent_at is not None
                    and o.claim_deadline is not None and now > o.claim_deadline):
                self._finalize(o, win=None, reason="等待确认超时", by="timeout")

    def tick(self) -> None:
        self._tick(self._clock())

    # ---------------- 查询 ----------------
    def summary(self) -> str:
        lines = []
        for o in sorted(self._cache.values(), key=lambda x: x.id):
            lines.append(
                f"#{o.id} [{o.status}] {o.otype or '?'} "
                f"{o.pages if o.pages is not None else '?'}页 "
                f"{o.amount if o.amount is not None else '?'}元 "
                f"| 来源:{o.source_group_name} | 设计师:{o.designer_name or '-'}"
                f" | 结果:{o.result_reason or '-'}"
            )
        return "\n".join(lines) if lines else "(暂无订单)"

    def status_of(self, order_id: int) -> Optional[Order]:
        return self._cache.get(order_id)

    # ---------------- 网页大厅数据接口 ----------------
    def orders_view(self) -> list[dict]:
        """供网页展示：全部订单列表（新单在前）。"""
        with self._lock:
            orders = sorted(self.store.list_all(), key=lambda x: -x.id)
            return [self._order_dict(o) for o in orders]

    def groups_view(self) -> list[dict]:
        return [
            {"id": gid, "name": g.get("name", gid), "claim_mode": g.get("claim_mode", "group")}
            for gid, g in self.source_groups.items()
        ]

    @staticmethod
    def _order_dict(o: Order) -> dict:
        return {
            "id": o.id,
            "status": o.status,
            "status_label": status_label(o.status),
            "otype": o.otype or "未分类",
            "pages": o.pages,
            "amount": o.amount,
            "note": o.note,
            "source_group_name": o.source_group_name,
            "raw": o.raw,
            "designer_name": o.designer_name or "",
            "claim_mode": o.claim_mode or "",
            "queue_pos": o.queue_pos,
            "result_reason": o.result_reason or "",
            "created_at": o.created_at,
        }
