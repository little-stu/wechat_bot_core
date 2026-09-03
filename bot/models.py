"""数据模型与订单状态常量。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------- 订单状态机 ----------------
# PENDING    待抢（已发布到大厅）
# CLAIMING   已抢待确认（设计师抢了，机器人正在企微上家群/私聊执行抢单动作，等待结果）
# WON        已抢到（等派单员拉群对接）
# LOST       抢单失败（通知设计师，订单关闭）
# MANUAL     超时/无法判定 -> 待人工确认
# CANCELLED  取消
STATUS_PENDING = "PENDING"
STATUS_CLAIMING = "CLAIMING"
STATUS_WON = "WON"
STATUS_LOST = "LOST"
STATUS_MANUAL = "MANUAL"
STATUS_CANCELLED = "CANCELLED"

ALL_STATUS = {
    STATUS_PENDING: "待抢",
    STATUS_CLAIMING: "已抢待确认",
    STATUS_WON: "已抢到",
    STATUS_LOST: "抢单失败",
    STATUS_MANUAL: "待人工确认",
    STATUS_CANCELLED: "已取消",
}

OPEN_STATUS = {STATUS_PENDING, STATUS_CLAIMING}

# ---------------- 抢单模式 ----------------
CLAIM_MODE_GROUP = "group"      # 回到企微上家群发话术
CLAIM_MODE_PRIVATE = "private"  # 私聊企微侧上家/派单人
CLAIM_MODE_MANUAL = "manual"    # 机器人无法发言(微信大群/别人企微群)：转派单员人工去群内抢单


@dataclass
class Inbound:
    """传输层进来的消息（两个 world 统一结构）。"""
    world: str                 # 'source'(企微) | 'ops'(个人微信)
    peer: str                  # 群 id 或联系人 id
    peer_name: str
    sender: str
    sender_name: str
    text: str
    is_group: bool
    ts: float
    at_me: bool = False

    def __str__(self) -> str:
        kind = f"群[{self.peer_name}]" if self.is_group else f"私聊[{self.sender_name}]"
        return f"<{self.world}|{kind} {self.sender_name}: {self.text[:60]}>"


@dataclass
class Order:
    """订单。state 以 dict 形态在 store/engine 中流转，这里仅定义结构说明。"""
    id: Optional[int] = None
    source_group: str = ""
    source_group_name: str = ""
    source_sender: str = ""
    source_sender_name: str = ""
    raw: str = ""
    otype: Optional[str] = None     # 需求类型（静态/动态/PPT...）
    pages: Optional[int] = None
    amount: Optional[float] = None
    note: str = ""
    status: str = STATUS_PENDING
    designer: Optional[str] = None
    designer_name: Optional[str] = None
    claim_mode: Optional[str] = None
    claim_sent_at: Optional[float] = None
    claim_deadline: Optional[float] = None
    result_reason: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    queue_pos: int = 0

    def no(self) -> str:
        return f"#{self.id}"


@dataclass
class SourceAnalysis:
    """对企微上家群一条消息的分析结论。"""
    is_order: bool = False
    otype: Optional[str] = None
    pages: Optional[int] = None
    amount: Optional[float] = None
    note: str = ""
    confidence: float = 0.0
    method: str = "rule"          # llm | rule
    reason: str = ""


@dataclass
class GrabAnalysis:
    """对个人微信侧抢单消息的分析结论。"""
    grabbed: bool = False
    order_id: Optional[int] = None
    needs_clarify: bool = False
    reason: str = ""
    method: str = "rule"


@dataclass
class Verdict:
    """对抢单结果的判定。"""
    win: bool = False
    lose: bool = False
    unknown: bool = True
    reason: str = ""
    method: str = "rule"


@dataclass
class TextCard:
    """发送给用户的文本消息。"""
    peer: str
    text: str


def status_label(status: str) -> str:
    return ALL_STATUS.get(status, status)
