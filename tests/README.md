# 测试

布局以 `docs/01-repo-structure.md` 为准。任务落地前，此目录只有本说明。

```
tests/
├── unit/          # pdf、xlsx、should-cost、rollup、风险规则、gate、渲染
├── agents/        # orchestrator 与四个 sub-agent
├── eval/          # 三个金样例与通过门槛
└── fixtures/      # case1、case2、case3 的 PDF、XLSX、meta.yaml
```

案例通过条件写在 `evals/README.md`。实现任务按 `tasks/40-iteration-loop.md` 的批次进入，不在本说明里预置失败或占位测试。每个任务结束时 `pytest tests/` 必须全绿，且测试不联网。
