"""个人微信侧真实接入（骨架，未联调）。

形态：你已有/将用的“个人微信 API 接入”（例如基于 ipad/pad 协议、hook + HTTP 网关、
或第三方聚合 API）。机器人账号是抢单大厅成员，且能私聊设计师/派单员。

接入需要三件事：
  1) 消息回调(webhook/长连接) -> self._emit(Inbound(world='ops', ...))
  2) send_text(peer, text)：给大厅群/设计师/派单员发消息
  3) 将实例传给 Engine 替换 MockTransport。

若你的 API 是 HTTP 型，通常实现为：注册一个接收地址，平台把消息 POST 进来，
这里把它转成 Inbound 再交给引擎；发送则 POST 到对方接口。
"""
from __future__ import annotations

import json
import time
import urllib.request
from typing import Any, Optional

from ..models import Inbound
from ..transport import Transport


class PersonalApiTransport(Transport):
    """个人微信 API 传输：真实实现请按你的网关契约填写。"""

    def __init__(self, cfg: dict[str, Any], api_base: Optional[str] = None,
                 token: Optional[str] = None):
        super().__init__(cfg, "ops")
        self.api_base = (api_base or "").rstrip("/")
        self.token = token or ""

    def start(self) -> None:
        if not self.api_base:
            raise RuntimeError(
                "个人微信 API 网关地址未配置。请在构造时传 api_base，"
                "并实现消息接收(webhook) -> self._emit(Inbound(world='ops', ...))。"
            )
        # TODO(接入): 启动长连接 / 暴露 webhook 接收地址，把消息转 Inbound 后 _emit
        raise NotImplementedError("个人微信 API 消息监听未实现，请按 README 接入")

    def from_webhook(self, body: dict[str, Any]) -> None:
        """若网关走 webhook：调用方(如 FastAPI/Flask 路由)把 body 转进来。"""
        msg = Inbound(
            world="ops",
            peer=str(body.get("peer") or body.get("roomid") or body.get("from")),
            peer_name=str(body.get("peer_name") or ""),
            sender=str(body.get("sender") or body.get("from")),
            sender_name=str(body.get("sender_name") or ""),
            text=str(body.get("content") or body.get("text") or ""),
            is_group=bool(body.get("is_group", False)),
            ts=time.time(),
        )
        self._emit(msg)

    def _post(self, path: str, payload: dict[str, Any]) -> dict:
        req = urllib.request.Request(
            f"{self.api_base}/{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     **({"Authorization": f"Bearer {self.token}"} if self.token else {})},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def send_text(self, peer: str, text: str) -> None:
        if not self.api_base:
            raise RuntimeError("个人微信 API 网关地址未配置")
        # TODO(接入): 字段名以你网关契约为准
        self._post("send_text", {"to": peer, "content": text})

    def send_file(self, peer: str, file_path: str) -> None:
        # TODO(接入): 视网关是否支持文件上传
        raise NotImplementedError("send_file 未接入")
