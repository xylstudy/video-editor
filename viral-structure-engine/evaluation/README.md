# Agent 运行评测

Web 的 Agent 流程使用同一个 `web_task_<task_id>` 运行目录记录两阶段：

1. 草案生成后，保存方案、素材清单、阶段日志和 `awaiting_confirmation` 报告。
2. 用户确认或修改分镜后，渲染脚本保存最终方案，重新调用 Reviewer 评估确认稿，并生成 `completed` 或 `failed` 报告。

报告位于 `data/runs/<run_id>/evaluation/report.json`。登录用户可通过 `GET /api/tasks/<task_id>/evaluation` 读取自己任务的报告。Reviewer 失败会写入错误和未通过的报告，不会抹掉已渲染的视频；渲染失败也会留下失败报告。

离线重新评测不会调用模型：

```powershell
cd viral-structure-engine
python -m evaluation.run_evaluator --run-dir data/runs/web_task_42
python -m evaluation.run_evaluator --runs-dir data/runs --min-score 80 --output data/evaluation-summary.json
```

最终报告检查阶段执行与失败记录、结构化产物、素材覆盖率、Reviewer 是否评估了最终方案、最终视频能否完整解码及其时长是否接近方案。它也记录阶段耗时、模型请求与重试次数，以及提供方返回的 token 用量。分数用于诊断；`success` 要求所有关键检查通过。`awaiting_confirmation` 报告使用 `ready_for_render` 表示草案阶段是否完整，不计入最终成功率。

渲染完成后还会写入 `render_reviewer/render_review.json`，它与 `reviewer/review_result.json` 分开：

1. `review_result.json` 是原有的 10 维分镜 Reviewer，评估方案预期的结构保真和剪辑质量。
2. `render_review.json` 是成片评测：先用 FFmpeg 全片解码，再检测疑似黑屏、长静帧、无音轨/静音，并按确认分镜时间轴提取代表帧。配置视觉模型时，模型会结合代表帧、确认分镜和参考结构给出实际成片的 Hook 呈现、分镜兑现、素材适配、转场节奏、连续性、字幕可读性和包装一致性等诊断，并对问题附秒级证据点。

疑似黑屏、静帧、无音轨属于诊断项，文本卡、静态照片和无配乐作品可能是合理创作选择；在尚未用人工标注基准集校准前，成片视觉分数也不会作为 `success` 的硬门槛。视觉模型未配置或调用失败时仍保存技术检查与抽帧证据，状态为 `skipped` 或 `failed`，不会删除已经渲染的视频。提供方不返回 token 用量时报告为 `null`，费用尚未纳入报告。
