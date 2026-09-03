"""企业微信侧真实接入（骨架，未联调）。

形态：企微客户端 Hook（例如 wcf/wechaty 企微版、com.github 等 hook 方案，
或自建基于企业微信客户端注入的消息通道）。机器人账号实际加入各上家群。

接入需要三件事：
  1) 消息回调 -> self._emit(Inbound(world='source', ...))，注意：
     - 过滤机器人自己发的消息（防止回声触发循环）
     - is_group=True 时 peer 用群 ID（如 xxx@chatroom），sender 为发送成员 wxid
     - is_group=False 时 peer/sender 为上家联系人的 wxid
  2) send_text(peer, text)：企微群发话术 / 私聊上家抢单话术
  3) 将 transport 实例传给 Engine，替换 MockTransport。

依赖的 hook 库不同，具体 API 各异；此文件作为接入契约示例，避免在核心引擎里写死。
"""
from __future__ import annotations

import time
from typing import Any

from ..models import Inbound
from ..transport import Transport


class WxWorkHookTransport(Transport):
    """企业微信侧传输：真实实现请在下方 TODO 处对接你的 hook 通道。"""

    def __init__(self, cfg: dict[str, Any], hook_client: Any = None):
        super().__init__(cfg, "source")
        self._client = hook_client

    def start(self) -> None:
        if self._client is None:
            raise RuntimeError(
                "企微 Hook 未配置：请传入 hook_client（企微客户端 hook 连接），"
                "并在本文件 start() 中注册“收到消息”回调 -> self._emit(Inbound(...))。"
            )
        # TODO(接入): 注册消息回调
        # 示例（伪代码，具体取决于 hook 库）:
        #   self._client.on_message = lambda raw: self._handle_raw(raw)
        raise NotImplementedError("企微 Hook 消息监听未实现，请按 README 接入")

    def _handle_raw(self, raw: Any) -> None:
        # TODO(接入): raw -> Inbound
        msg = Inbound(
            world="source",
            peer=str(raw.group_id) if raw.is_group else str(raw.sender),
            peer_name=getattr(raw, "group_name", "") or str(raw.group_id),
            sender=str(raw.sender),
            sender_name=getattr(raw, "sender_name", "") or str(raw.sender),
            text=getattr(raw, "content", ""),
            is_group=bool(getattr(raw, "is_group", False)),
            ts=time.time(),
        )
        self._emit(msg)

    def send_text(self, peer: str, text: str) -> None:
        if self._client is None:
            raise RuntimeError("企微 Hook 未配置")
        # TODO(接入): self._client.send_text(peer, text)
        raise NotImplementedError("send_text 未接入")

    def send_file(self, peer: str, file_path: str) -> None:
        raise NotImplementedError("send_file 未接入")
