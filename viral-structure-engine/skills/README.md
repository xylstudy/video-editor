# Editing Skill learning pipeline

这套代码把 Skill 的“发现 → 应用 → 评估 → 迭代”拆成可审计阶段。在线任务结束时，`OutputManager` 会自动从结构化产物抽取经验；离线命令负责挖掘、实验和版本治理。原始图片/视频不会写入经验数据库，长期保存的是 Gene、MaterialGene、剪辑动作和评测结果。

## 常用命令

在 `viral-structure-engine` 目录执行：

```bash
python -m skills.pipeline ingest
python -m skills.pipeline mine --min-samples 10
python -m skills.pipeline experiment-create --candidate <candidate-id> --dataset skills/experiments/fixed_task_set.example.json
python -m skills.pipeline experiment-record --experiment <experiment-id> --case <case-id> --variant baseline --result baseline-result.json
python -m skills.pipeline experiment-record --experiment <experiment-id> --case <case-id> --variant candidate --result candidate-result.json
python -m skills.pipeline experiment-analyse --experiment <experiment-id>
python -m skills.pipeline promote --candidate <candidate-id> --experiment <experiment-id>
python -m skills.pipeline learn-weights
python -m skills.pipeline rollback --skill hook --version 1.0.0
```

实验结果 JSON 至少包含 `quality_score`，建议同时写入 `latency_seconds` 和 `cost`。晋升默认必须同时通过候选结构校验、观察样本门槛和配对实验门槛；`--force` 仅用于有审计记录的人工紧急处置。

## 关键边界

- 历史聚合产生的是候选，不是因果结论。
- `selected / loaded / declared / verified` 不得合并成一个“used”字段。
- 学得的 `routing_weight` 只调整语义候选顺序，不能删除 Gene 确定性必选项。
- 版本晋升前归档旧 Registry 定义和 Markdown，支持显式回滚。
