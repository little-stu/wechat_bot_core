"""传输层抽象：世界分两侧。
  world='source' -> 企业微信侧（上家群 / 上家私聊），真实形态=企微客户端 Hook
  world='ops'    -> 个人微信侧（抢单大厅 / 设计师 / 派单员），真实形态=个人微信 API
引擎只依赖 Transport 接口与 Inbound 消息，不关心真实实现，便于 Mock 先行、后续切换。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from .models import Inbound


class Transport:
    world: str = "?"

    def __init__(self, cfg: dict[str, Any], world: str):
        self.cfg = cfg
        self.world = world
        self._handler: Optional[Callable[[Inbound], None]] = None

    # ---- 由真实适配器/Mock 调用：注册收到消息的回调 ----
    def on_message(self, handler: Callable[[Inbound], None]) -> None:
        self._handler = handler

    def _emit(self, msg: Inbound) -> None:
        if self._handler:
            self._handler(msg)

    # ---- 引擎调用：发送 ----
    def send_text(self, peer: str, text: str) -> None:
        raise NotImplementedError

    def send_file(self, peer: str, file_path: str) -> None:
        raise NotImplementedError

    def display_name(self, peer: str) -> str:
        return peer

    def start(self) -> None:
        """真实适配器：建立连接/开始监听。Mock 无操作。"""
        pass

    def stop(self) -> None:
        pass
