"""消息解读器：LLM 优先，规则降级兜底（无 Key/失败时保证可用）。
职责分三块：
  1) 企微上家群消息 -> 是否新订单 + 结构化字段（SourceAnalysis）
  2) 个人微信侧消息 -> 是否抢单 + 指向哪个订单（GrabAnalysis）
  3) 企微侧抢单后的确认消息 -> win/lose/unknown（Verdict）
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .llm import LLMClient
from .models import GrabAnalysis, Order, SourceAnalysis, Verdict
from . import prompts

# 常见设计类型关键词（规则用）
TYPE_KEYWORDS = [
    "静态", "动态", "PPT", "美化", "详情页", "长图", "海报", "封面",
    "视频", "剪辑", "排版", "Logo", "logo", "画册", "H5", "小程序", "UI", "电商",
]

_AMOUNT_RE = re.compile(r"(?:总金额|金额|报价|价格)\s*[:：]?\s*(\d+(?:\.\d+)?)")
_AMOUNT2_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:元|块|rmb|RMB)")
_PAGES_RE = re.compile(r"(\d+)\s*页")
_ORDER_ID_RE = re.compile(r"(?:抢|接|要|领)\s*(?:单|这单)?\s*[#＃号]?\s*(\d+)")
_GRAB_WORD_RE = re.compile(r"(?:抢|接单|领单|我要|我来)")

_WIN_RE = re.compile(r"(抢到|成交|给你|确认|没问题|好的.*给|ok|OK|已.*给|拍给|你的)")
_LOSE_RE = re.compile(r"(没抢到|被抢|已被|拍走|给别人|没了|没有了|已经.*人|满了|抱歉|晚了|错过)")


def _clean(text: str) -> str:
    t = re.sub(r"@所有人|@all", "", text)
    return re.sub(r"\s+", " ", t).strip()


def _first_type(text: str) -> Optional[str]:
    for kw in TYPE_KEYWORDS:
        if kw in text:
            return kw
    return None


class Interpreter:
    def __init__(self, cfg: dict[str, Any], llm: LLMClient):
        self.cfg = cfg
        self.llm = llm

    # ---------------- 1) 企微上家群 -> 新订单 ----------------
    def analyze_source(self, text: str, group_name: str = "", sender_name: str = "",
                       recent: Optional[list[str]] = None) -> SourceAnalysis:
        res = self._rule_source(text)
        if not self.llm.enabled:
            return res
        recent_txt = "\n".join(f"- {r}" for r in (recent or [])[-8:]) or "(无)"
        user = prompts.USER_SOURCE_TMPL.format(
            group_name=group_name, sender_name=sender_name, text=text, recent=recent_txt
        )
        obj = self.llm.chat_json(prompts.SYS_SOURCE, user)
        if not obj:
            return res
        try:
            is_order = bool(obj.get("is_order"))
        except Exception:
            is_order = res.is_order
        return SourceAnalysis(
            is_order=is_order,
            otype=obj.get("otype") or None,
            pages=int(obj["pages"]) if obj.get("pages") not in (None, "") else None,
            amount=float(obj["amount"]) if obj.get("amount") not in (None, "") else None,
            note=str(obj.get("note") or "").strip(),
            confidence=1.0 if is_order else 0.0,
            method="llm",
            reason=str(obj.get("reason") or ""),
        )

    def _rule_source(self, text: str) -> SourceAnalysis:
        t = _clean(text)
        amount = _AMOUNT_RE.search(t) or _AMOUNT2_RE.search(t)
        pages = _PAGES_RE.search(t)
        otype = _first_type(t)

        has_money = amount is not None
        has_pages = pages is not None
        is_order = bool(has_pages or has_money)

        # 规则低置信度过滤：仅"接单""设计""美化"等词而无数字，不判为订单
        if not is_order:
            is_order = False

        note = t
        note = re.sub(r"(?:总金额|金额|报价|价格)\s*[:：]?\s*\d+(?:\.\d+)?", "", note)
        note = re.sub(r"\d+(?:\.\d+)?\s*(?:元|块)", "", note)
        note = re.sub(r"\d+\s*页", "", note)
        note = re.sub(r"(接的私|私聊|私我|接单|可接|加我|V我|微信)", " ", note)
        for kw in TYPE_KEYWORDS:
            note = note.replace(kw, " ")
        note = re.sub(r"\s+", " ", note).strip(" ，,。！!?？")

        return SourceAnalysis(
            is_order=is_order,
            otype=otype,
            pages=int(pages.group(1)) if pages else None,
            amount=float(amount.group(1)) if amount else None,
            note=note,
            confidence=1.0 if is_order else 0.0,
            method="rule",
            reason="含页数或金额关键词" if is_order else "无订单特征",
        )

    # ---------------- 2) 个人微信 -> 抢单 ----------------
    def analyze_grab(self, text: str, candidates: list[Order], channel: str,
                     sender_name: str = "") -> GrabAnalysis:
        res = self._rule_grab(text, candidates)
        if res.grabbed or res.needs_clarify or not self.llm.enabled:
            return res
        # 规则无法解析且有候选，交给 LLM
        lines = "\n".join(
            f"- id={o.id}: {o.otype or '未知类型'} {o.pages or '?'}页 金额{o.amount or '?'}"
            for o in candidates
        )
        user = prompts.USER_GRAB_TMPL.format(
            sender_name=sender_name, channel=channel, text=text,
            orders=lines or "(无候选)",
        )
        obj = self.llm.chat_json(prompts.SYS_GRAB, user)
        if not obj:
            return res
        try:
            oid = int(obj["order_id"]) if obj.get("order_id") not in (None, "") else None
        except Exception:
            oid = res.order_id
        return GrabAnalysis(
            grabbed=bool(obj.get("grabbed")) and oid is not None,
            order_id=oid,
            needs_clarify=bool(obj.get("needs_clarify")),
            reason=str(obj.get("reason") or ""),
            method="llm",
        )

    def _rule_grab(self, text: str, candidates: list[Order]) -> GrabAnalysis:
        t = _clean(text)
        m = _ORDER_ID_RE.search(t)
        if m:
            oid = int(m.group(1))
            return GrabAnalysis(grabbed=True, order_id=oid, needs_clarify=False,
                                reason=f"规则命中订单号 #{oid}", method="rule")
        # 无显式编号
        if _GRAB_WORD_RE.search(t) and candidates:
            if len(candidates) == 1:
                o = candidates[0]
                return GrabAnalysis(grabbed=True, order_id=o.id, needs_clarify=False,
                                    reason="唯一候选自动命中", method="rule")
            return GrabAnalysis(grabbed=False, order_id=None, needs_clarify=True,
                                reason="多笔候选需指明单号", method="rule")
        return GrabAnalysis(grabbed=False, order_id=None, needs_clarify=False,
                            reason="无抢单意图", method="rule")

    # ---------------- 3) 企微确认消息 -> 判定 ----------------
    def verdict(self, text: str, order: Order, phrase: str = "",
                recent: Optional[list[str]] = None) -> Verdict:
        res = self._rule_verdict(text)
        if (not res.unknown) or not self.llm.enabled:
            return res
        order_desc = f"#{order.id} {order.otype or ''} {order.pages or '?'}页 金额{order.amount or '?'}"
        recent_txt = "\n".join(f"- {r}" for r in (recent or [])[-8:]) or "(无)"
        user = prompts.USER_VERDICT_TMPL.format(
            order_desc=order_desc, phrase=phrase, text=text, recent=recent_txt
        )
        obj = self.llm.chat_json(prompts.SYS_VERDICT, user)
        if not obj:
            return res
        v = str(obj.get("verdict") or "unknown")
        return Verdict(
            win=v == "win", lose=v == "lose", unknown=v == "unknown",
            reason=str(obj.get("reason") or ""), method="llm",
        )

    def _rule_verdict(self, text: str) -> Verdict:
        # 先查失败词：避免“没抢到/没抢上/被抢了”里的子串“抢到/抢了”误判为成功
        if _LOSE_RE.search(text):
            return Verdict(win=False, lose=True, unknown=False,
                           reason="命中失败关键词", method="rule")
        if _WIN_RE.search(text):
            return Verdict(win=True, lose=False, unknown=False,
                           reason="命中抢到关键词", method="rule")
        return Verdict(win=False, lose=False, unknown=True,
                       reason="无明确关键词", method="rule")
