"""组装入口：根据配置构建 Engine 与两侧传输。

Mock 模式（默认）:
    engine = app.build(cfg)
真实接入（接入顺序：先企微后个微）:
    source_t = WxWorkHookTransport(cfg, hook_client=...)
    ops_t = PersonalApiTransport(cfg, api_base=..., token=...)
    engine = app.build(cfg, source=source_t, ops=ops_t)
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from .config import load_config
from .engine import Engine
from .interpreter import Interpreter
from .llm import LLMClient
from .mock_transport import MockTransport
from .store import Store
from .transport import Transport


def build(
    cfg: dict[str, Any],
    db_path: Optional[str | Path] = None,
    source: Optional[Transport] = None,
    ops: Optional[Transport] = None,
    clock=None,
) -> Engine:
    if db_path is None:
        data_dir = Path(cfg.get("bot", {}).get("data_dir_abs", "data"))
        db_path = data_dir / "bot.db"
    store = Store(db_path)
    llm = LLMClient(cfg)
    interp = Interpreter(cfg, llm)

    source_t = source or MockTransport(cfg, "source", tag="企微")
    ops_t = ops or MockTransport(cfg, "ops", tag="微信")
    transports = {"source": source_t, "ops": ops_t}

    engine = Engine(cfg, store, interp, transports, clock=clock)
    source_t.on_message(engine.on_inbound)
    ops_t.on_message(engine.on_inbound)
    return engine
