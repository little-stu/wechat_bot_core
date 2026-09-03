"""交互式控制台：手动注入消息，观察机器人全流程反应（Mock 模式）。

运行: python run_console.py

通道前缀:
  A> 文本     企微上家A群消息（A老板发言）
  B> 文本     企微上家B群消息（B老板发言）
  A私> 文本   A老板私聊机器人（企微侧）
  B私> 文本   B老板私聊机器人（企微侧）
  H1> 文本    设计师-小张 在大厅群发言
  H2> 文本    设计师-小李 在大厅群发言
  D1> 文本    设计师-小张 私聊机器人
  D2> 文本    设计师-小李 私聊机器人
  P> 文本     派单员 私聊机器人（人工确认: 确认 #单号 成功/失败）
控制命令:
  orders  查看订单状态汇总    help  帮助    quit  退出

示例:
  A> @所有人 优质静态6页 总金额60 接的私
  H1> 抢 #1
  A> @机器人 抢到了
"""
from __future__ import annotations

import sys

from bot import app
from bot.config import PROJECT_ROOT, load_config

CHANNELS: dict[str, tuple[str, str, str, bool]] = {
    # channel -> (world, peer, sender, is_group)
    "A":  ("source", "wxg_a", "wxc_a", True),
    "B":  ("source", "wxg_b", "wxc_b", True),
    "A私": ("source", "wxc_a", "wxc_a", False),
    "B私": ("source", "wxc_b", "wxc_b", False),
    "H1": ("ops", "g_hall", "d1", True),
    "H2": ("ops", "g_hall", "d2", True),
    "D1": ("ops", "d1", "d1", False),
    "D2": ("ops", "d2", "d2", False),
    "P":  ("ops", "dispatcher", "dispatcher", False),
}


def main() -> int:
    cfg = load_config()
    engine = app.build(cfg, db_path=PROJECT_ROOT / "data" / "console.sqlite3")
    src = engine.transports["source"]
    ops = engine.transports["ops"]

    print("微信订单机器人 · 交互控制台（Mock）  输入 help 查看用法，quit 退出")
    while True:
        try:
            raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见")
            break
        if not raw:
            continue
        if raw.lower() in ("quit", "exit", "q"):
            print("再见")
            break
        if raw == "orders":
            print(engine.summary())
            continue
        if raw in ("help", "?"):
            print(__doc__)
            continue

        if ">" not in raw:
            print("格式: 通道> 文本，例如  A> @所有人 优质静态6页 总金额60 接的私")
            continue
        channel, _, text = raw.partition(">")
        channel = channel.strip().upper()
        text = text.strip()
        if not text:
            continue
        spec = CHANNELS.get(channel)
        if spec is None:
            print(f"未知通道 {channel!r}，可用: {', '.join(CHANNELS)}")
            continue
        world, peer, sender, is_group = spec
        transport = src if world == "source" else ops
        transport.inject(peer, sender, text, is_group=is_group)
        engine.tick()

    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
