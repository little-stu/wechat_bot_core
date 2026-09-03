"""Mock 传输层：在控制台模拟企微/个人微信两侧的群聊与私聊，用于全流程演示与联调。
真实接入时替换为 bot/adapters/wxwork_hook.py 与 personal_api.py 中的实现即可。
"""
from __future__ import annotations

import time
from typing import Any

from .config import get_designers, get_dispatcher, get_hall, get_source_groups
from .models import Inbound
from .transport import Transport


class MockTransport(Transport):
    def __init__(self, cfg: dict[str, Any], world: str, tag: str = "企微"):
        super().__init__(cfg, world)
        self.tag = tag
        self.bot_name = cfg.get("bot", {}).get("name", "机器人")
        self.at_keywords = cfg.get("bot", {}).get("at_keywords", ["机器人"])
        self._names: dict[str, str] = {}
        self._build_names()

    def _build_names(self) -> None:
        if self.world == "source":
            for gid, g in get_source_groups(self.cfg).items():
                self._names[gid] = g.get("name", gid)
                self._names[g.get("owner", gid)] = g.get("owner_name", g.get("owner", gid))
        else:
            hall = get_hall(self.cfg)
            if hall:
                self._names[hall.get("id", "g_hall")] = hall.get("name", "抢单大厅")
            for cid, info in get_designers(self.cfg).items():
                self._names[cid] = info.get("name", cid)
            disp = get_dispatcher(self.cfg)
            if disp:
                self._names[disp.get("id", "dispatcher")] = disp.get("name", "派单员")

    # ---- 供演示/控制台注入消息 ----
    def inject(self, peer: str, sender: str, text: str, is_group: bool) -> None:
        at_me = any(k in text for k in self.at_keywords) or (self.bot_name in text)
        msg = Inbound(
            world=self.world,
            peer=peer,
            peer_name=self.display_name(peer),
            sender=sender,
            sender_name=self.display_name(sender),
            text=text,
            is_group=is_group,
            ts=time.time(),
            at_me=at_me,
        )
        arrow = "群" if is_group else "私聊"
        print(f"[模拟 {self.tag}接收] {arrow} {msg.peer_name} / {msg.sender_name}: {text}")
        self._emit(msg)

    # ---- 输出 ----
    def send_text(self, peer: str, text: str) -> None:
        print(f"[模拟 {self.tag}发送] -> {self.display_name(peer)}:\n{text}\n{'-' * 56}")

    def send_file(self, peer: str, file_path: str) -> None:
        print(f"[模拟 {self.tag}发送文件] -> {self.display_name(peer)}: {file_path}")

    def display_name(self, peer: str) -> str:
        return self._names.get(peer, peer)
