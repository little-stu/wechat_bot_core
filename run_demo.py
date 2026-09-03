"""端到端脚本演示：Mock 企微 + Mock 微信，模拟完整业务链路并自动校验。

运行: python run_demo.py
（可用 DEEPSEEK_API_KEY 环境变量开启真实大模型解读；无 Key 时规则解析兜底。）
"""
from __future__ import annotations

import sys
import time

from bot import app
from bot.config import PROJECT_ROOT, load_config
from bot.models import STATUS_LOST, STATUS_PENDING, STATUS_WON

# 用假时钟，便于演示超时分支而不真的等待
class FakeClock:
    def __init__(self, t0: float = 1_700_000_000.0):
        self.t = t0

    def now(self) -> float:
        return self.t

    def advance(self, sec: float) -> None:
        self.t += sec


def main() -> int:
    print("=" * 64)
    print("微信订单机器人 · 端到端演示（Mock 企微 / Mock 微信 / DeepSeek 可插拔）")
    print("=" * 64)

    cfg = load_config()          # config.json 或 config.example.json
    cfg.setdefault("claim", {})["timeout_sec"] = 30  # 演示用短超时
    clock = FakeClock()

    db_file = PROJECT_ROOT / "data" / "demo.sqlite3"
    if db_file.exists():
        db_file.unlink()          # 删除旧库：引擎从空缓存/空库启动，订单编号从 #1 起
    engine = app.build(cfg, db_path=db_file, clock=clock.now)
    src = engine.transports["source"]
    ops = engine.transports["ops"]

    ok: list[tuple[str, bool, str]] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        ok.append((name, cond, detail))
        print(f"[校验] {'PASS' if cond else 'FAIL'} | {name} {detail}")

    def new_order(group: str, owner: str, text: str) -> None:
        print(f"\n-- 企微上家群来单 --")
        src.inject(group, owner, text, is_group=True)

    def owner_says(group: str, owner: str, text: str) -> None:
        print(f"\n-- 企微群内消息 --")
        src.inject(group, owner, text, is_group=True)

    def owner_private(owner: str, text: str) -> None:
        print(f"\n-- 企微上家私聊机器人 --")
        src.inject(owner, owner, text, is_group=False)

    def hall_says(designer: str, text: str) -> None:
        print(f"\n-- 设计师在大厅说话 --")
        ops.inject("g_hall", designer, text, is_group=True)

    def designer_private(designer: str, text: str) -> None:
        print(f"\n-- 设计师私聊机器人 --")
        ops.inject(designer, designer, text, is_group=False)

    def dispatcher_says(text: str) -> None:
        print(f"\n-- 派单员私聊机器人 --")
        ops.inject("dispatcher", "dispatcher", text, is_group=False)

    # ============ 场景1: 企微A群(group 抢单) 成功 ============
    new_order("wxg_a", "wxc_a", "@所有人 优质静态6页 总金额60 接的私")
    o1 = engine.status_of(1)
    check("场景1-来单解析入厅", o1 is not None and o1.status == STATUS_PENDING, f"#1 status={o1.status if o1 else None}")

    hall_says("d1", "@机器人 抢 #1")
    o1 = engine.status_of(1)
    check("场景1-设计师抢单锁定", o1 is not None and o1.status != STATUS_PENDING and o1.designer == "d1",
          f"#1 designer={o1.designer if o1 else None}")

    owner_says("wxg_a", "wxc_a", "@机器人 抢到了")
    o1 = engine.status_of(1)
    check("场景1-group 抢单成功", o1 is not None and o1.status == STATUS_WON, f"#1 status={o1.status if o1 else None}")

    # ============ 场景2: 企微B群(private 抢单) 成功 ============
    new_order("wxg_b", "wxc_b", "@所有人 优质动态10页 总金额120 接的私")
    o2 = engine.status_of(2)
    check("场景2-来单解析入厅", o2 is not None and o2.status == STATUS_PENDING, f"#2 status={o2.status if o2 else None}")

    designer_private("d2", "抢 #2")
    o2 = engine.status_of(2)
    check("场景2-设计师私聊抢单锁定", o2 is not None and o2.claim_mode == "private" and o2.designer == "d2",
          f"#2 mode={o2.claim_mode if o2 else None}")

    owner_private("wxc_b", "给你了，这单归你")
    o2 = engine.status_of(2)
    check("场景2-private 抢单成功", o2 is not None and o2.status == STATUS_WON, f"#2 status={o2.status if o2 else None}")

    # ============ 场景3: A群 再来两单，串行排队 + 一成一败 ============
    new_order("wxg_a", "wxc_a", "@所有人 高级动态8页 总金额90 接的私")     # -> #3
    hall_says("d1", "抢 #3")                                             # 立即抢 #3（A群空闲）
    o3 = engine.status_of(3)
    check("场景3-设计师抢#3", o3 is not None and o3.status != STATUS_PENDING, f"#3 status={o3.status if o3 else None}")

    new_order("wxg_a", "wxc_a", "@所有人 精美静态10页 总金额110 接的私")   # -> #4（此时#3在途）
    hall_says("d2", "我要 #4")                                           # 同群排队
    o4 = engine.status_of(4)
    check("场景3-同群抢单排队", o4 is not None and o4.queue_pos > 0, f"#4 queue_pos={o4.queue_pos if o4 else None}")

    owner_says("wxg_a", "wxc_a", "@机器人 没抢到，给别人了")               # #3 失败
    o3 = engine.status_of(3)
    check("场景3-#3抢单失败", o3 is not None and o3.status == STATUS_LOST, f"#3 status={o3.status if o3 else None}")
    o4 = engine.status_of(4)
    check("场景3-#4自动出队开抢", o4 is not None and o4.queue_pos == 0 and o4.claim_sent_at is not None,
          f"#4 queue_pos={o4.queue_pos if o4 else None}")

    owner_says("wxg_a", "wxc_a", "@机器人 抢到了")                        # #4 成功
    o4 = engine.status_of(4)
    check("场景3-#4抢单成功", o4 is not None and o4.status == STATUS_WON, f"#4 status={o4.status if o4 else None}")

    # ============ 场景4: 超时 -> 人工确认 ============
    new_order("wxg_a", "wxc_a", "@所有人 普通静态3页 总金额25 接的私")     # -> #5
    designer_private("d1", "抢 #5")
    o5 = engine.status_of(5)
    check("场景4-#5抢单中", o5 is not None and o5.claim_sent_at is not None, f"#5 claim_sent={o5.claim_sent_at if o5 else None}")

    clock.advance(60)   # 超过 timeout_sec=30
    engine.tick()
    o5 = engine.status_of(5)
    check("场景4-超时进入人工确认", o5 is not None and o5.status == "MANUAL", f"#5 status={o5.status if o5 else None}")

    dispatcher_says("确认 #5 成功")
    o5 = engine.status_of(5)
    check("场景4-派单员人工确认成功", o5 is not None and o5.status == STATUS_WON, f"#5 status={o5.status if o5 else None}")

    # ============ 场景5: 去重 ============
    count_before = len(engine.store.list_all())
    new_order("wxg_a", "wxc_a", "@所有人 优质静态6页 总金额60 接的私")     # 与#1重复
    count_after = len(engine.store.list_all())
    check("场景5-重复订单被忽略", count_after == count_before, f"orders {count_before} -> {count_after}")

    # ============ 结果汇总 ============
    print("\n" + "=" * 64)
    print("订单状态汇总（引擎内存 & SQLite）")
    print("-" * 64)
    print(engine.summary())
    print("=" * 64)

    failed = [name for name, cond, _ in ok if not cond]
    print(f"演示完成：{len(ok) - len(failed)}/{len(ok)} 项通过")
    if failed:
        print("未通过:", failed)
        return 1
    print("全部通过 ✓")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
