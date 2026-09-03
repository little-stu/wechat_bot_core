# 微信订单机器人 · 核心版（纯微信消息流程，无网页）

本文件夹是从 `D:\机器人接入\wechat_order_bot` 中抽取的**核心源码版**：
只保留"企微读单 → AI解析 → 个人微信抢单大厅 → 机器人抢单 → 结果回报"的
纯消息驱动流程，不含后来新增的网页大厅（`run_web.py` / `bot/web_hall.py`）。

## 运行（零第三方依赖，Python 3.9+）

```powershell
cd D:\机器人接入\wechat_bot_core
python run_demo.py        # 端到端自动演示（15 项流程校验）
python run_console.py     # 交互控制台：手动扮演上家/设计师/派单员
```

或直接双击 `start_demo.bat`。

可选：接 DeepSeek 真实大模型解读（不配 Key 也能跑，规则解析兜底）：

```powershell
$env:DEEPSEEK_API_KEY="sk-你的key"
python run_demo.py
```

模型默认 `deepseek-chat`（可改 `config.json` 的 `deepseek.model / base_url`）。

## 控制台玩法（run_console.py）

```
A>  @所有人 优质静态6页 总金额60 接的私     # 企微上家A群来单（A老板）
H1> 抢 #1                                  # 设计师-小张在大厅抢单
A>  @机器人 抢到了                          # A老板群里确认 → 机器人判定成功
B>  @所有人 优质动态10页 总金额120 接的私   # B群为 private 模式：机器人会私聊B老板
D2> 抢 #2
B私> 给你了，这单归你                       # B老板私聊确认
P>  确认 #5 成功                            # 派单员人工确认（超时兜底）
orders                                      # 查看全部订单状态
```

可用通道：`A` `B`（企微群）、`A私` `B私`（企微老板私聊）、`H1` `H2`（大厅）、
`D1` `D2`（设计师私聊）、`P`（派单员）。

## 目录结构（核心）

```
wechat_bot_core/
├─ config.json                 # 群/设计师/话术/超时/模型配置
├─ run_demo.py                 # 端到端演示
├─ run_console.py              # 交互控制台
├─ bot/
│  ├─ engine.py                # 核心状态机与业务编排
│  ├─ interpreter.py           # LLM+规则双通道解读（订单/抢单/结果）
│  ├─ llm.py                   # DeepSeek 客户端（OpenAI 兼容，urllib）
│  ├─ notifier.py              # 对外文案
│  ├─ store.py                 # SQLite 持久化
│  ├─ transport.py             # 传输抽象
│  ├─ mock_transport.py        # Mock 模拟收发（企微/微信双侧）
│  ├─ models.py / config.py / prompts.py / app.py
│  └─ adapters/                # 真实接入骨架（企微Hook/个微API）
```

> 注意：`config.json` 中的来源群、设计师、派单员均为**演示用假 ID**，
> 真实接入微信时按 README(根目录大版本)第 5 节替换成真实账号 ID。
