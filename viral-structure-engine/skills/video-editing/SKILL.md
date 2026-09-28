---
name: video-editing
description: 跨任务复用的短视频剪辑决策知识（Hook / 节奏 / 转场 / 情绪 / 素材匹配 / 结构适配 / 字幕包装）。
when_to_use: 当 Planner 需要把 Reference Gene 适配到用户素材并做出具体剪辑决策时，按需加载对应 reference。
priority: 用户显式要求 > Reference Gene > Editing Skill > 模型自由发挥
---

# video-editing Skill

## 定位

本 Skill 沉淀**跨任务复用**的剪辑经验，帮助 Planner 回答"在用户素材条件下，怎么把
Reference Gene 的结构功能剪好"。它**不**描述本次参考视频要保留什么结构——那是
Reference Gene 的职责。

| | Reference Gene | Editing Skill |
|---|---|---|
| 作用域 | 当前参考视频专属 | 跨任务长期复用 |
| 决定什么 | 迁移**什么结构**（功能/节奏/情绪骨架） | **怎么剪好**（具体手法/替代策略） |
| 约束性质 | 硬约束为主 | 软策略为主 |
| 可否被覆盖 | 仅用户显式要求可覆盖 | 可被 Gene 硬约束覆盖 |

## 使用时机

只在 Planner 做具体剪辑决策、且确定性路由命中时加载对应 reference。**不要在任务开始
时把全部知识注入 prompt。**

## 路由规则（确定性必选，LLM 语义补充）

| 当前决策 | 加载 reference |
|---|---|
| 规划 Opening Hook / hook 镜头 | `hook.md` |
| 选择镜头节奏 / pacing | `rhythm.md` |
| 选择转场 | `transition.md` |
| 设计情绪弧 / 情绪连贯 | `emotion.md` |
| Gene 所需镜头与用户素材无法直接匹配 | `material-matching.md` |
| 原结构需在用户素材条件下变形 | `structure-adaptation.md` |
| 字幕 / 包装 / 文字卡 | `subtitle.md` |

对应实现见 `skills/router.py`：`route_for_stage` / `route_for_shot` / `route_for_gene`。

正式规划路径使用 `route_hybrid`：上述 Gene 规则结果不可被 LLM 删除；LLM 只根据用户目标、
Gene、脱敏素材摘要和 Registry description 补充相关的 active reference。语义调用失败时退回
规则结果，最终只读取命中的 Markdown。

## 优先级与覆盖规则（重要）

1. **用户显式要求** 永远最高。
2. **Reference Gene 的硬约束**（`hard_constraints` / `importance=critical`）优先于任何 Skill 建议。
3. Skill 只在 Gene 的**软偏好**层面、或 Gene 未约束的自由度上给出策略。
4. 当 Skill 的"常见做法"与 Gene 硬约束冲突时，**放弃 Skill，保持 Gene**。

> 示例：Gene 明确要求第 1 镜是 `establishing`（场景建立），即便 Skill 里推荐"开场用
> 人物特写 + 金句 Hook"，Planner 也必须先满足 establishing 功能，再谈 Hook 表现。
