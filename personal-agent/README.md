# Personal Agent

一个可自托管、可审计、可替换模型的个人 AI Agent，对标 Meta Muse。默认 LLM 为 **DeepSeek**（OpenAI 兼容接口）。

- **长时目标**：给一个目标 → 规划 → 逐步执行；事件溯源存储，进程崩溃/重启后从断点继续。
- **个人记忆**：从你本人的话中抽取事实与偏好；回复可溯源到具体记忆；可逐条删除、导出。
- **Sentinel**：每个动作执行前都过确定性规则（能力授权、出网白名单、SSRF、敏感数据外发、限速、风险分级）。
- **审批**：R3（对外可见/不可撤销，如发邮件）必须通过结构化命令批准；文字"同意"无效。
- **凭据保险库**：AES-GCM 加密；Agent 与 LLM 只看到 handle，凭据只注入沙箱子进程，输出自动脱敏。
- **审计**：hash 链只追加日志，可校验防篡改。

设计文档见 [`docs/`](docs/README.md)。

## 一键运行

```bash
cd personal-agent
pip install -e ".[dev]"
cp .env.example .env   # 填 PA_LLM_API_KEY（DeepSeek key）、PA_VAULT_PASSPHRASE
set -a && . ./.env && set +a
pa                      # 启动 CLI
```

CLI 命令：`/approve <审批id>`、`/reject <审批id>`、`/cancel <goal_id>`、`/goals`、`/memories`、
`/forget <memory_id>`、`/confirm <memory_id>`、`/audit <goal_id>`、`/vault-add <service> <scope,...>`、`/resume`。

邮件凭据示例（`/vault-add mail mail.read,mail.send` 后粘贴，不回显）：
```json
{"imap_host": "imap.example.com", "smtp_host": "smtp.example.com", "smtp_port": 465,
 "username": "me@example.com", "password": "app-password"}
```

## 模型配置

| 用途 | 环境变量 | 默认 |
|---|---|---|
| 规划/步骤执行 | `PA_MODEL_PLANNER` | `deepseek-v4-pro` |
| 路由 | `PA_MODEL_ROUTER` | `deepseek-flash` |
| 记忆抽取 | `PA_MODEL_MEMORY` | `deepseek-flash` |
| 对话/总结 | `PA_MODEL_CHAT` | `deepseek-flash` |

换任意 OpenAI 兼容服务：改 `PA_LLM_BASE_URL` 和模型名即可（本地 vLLM / Ollama 亦可）。

## 架构

```
消息 → Router ─chat→ 记忆召回 + 回复
          └new_goal→ GoalEngine(事件溯源) → Planner → Executor 提议动作
                                                  │
                                            Sentinel 规则判定
                          allow ↙          needs_approval ↓        ↘ deny（回灌给 LLM）
                  ToolRunner(沙箱子进程 + Vault 注入 + 脱敏)   ApprovalGate → 用户 /approve
                                  ↓
                       结果（外部内容标记 untrusted）→ 下一步 → 总结
```

## 开发

```bash
pytest --cov=personal_agent   # 67 个测试，含 4 个用户故事 + 11 个注入用例的 eval
ruff check . && mypy          # mypy --strict
```

## 当前版本（v0.1）范围与遗留
见 [`docs/05-roadmap.md`](docs/05-roadmap.md) 的"实现状态"。
