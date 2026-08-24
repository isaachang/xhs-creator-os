---
name: xhs-image
description: 根据小红书正文先规划封面，再调用仓库内置的 Baoyu 图片模块生成图片卡片，并对封面和知识卡执行独立结构审查。
---

# 小红书生图适配层

本 Skill 是 Creator OS 唯一的图片流程入口与质量闸门。它不复制或替代 `third_party/baoyu-xhs-images` 的生成规则：Baoyu 负责按已确认 Prompt 生成图片；本 Skill 负责正文分析、封面确认、资产路由、阶段推进和审查状态输出。

## 触发条件

只有用户明确要求“生图”“图片卡片”“小红书配图”或“审图”时使用。调研、仿写和 Compare 不自动触发本 Skill。

## 执行规则

1. 读取 `../../references/account-context.md`，理解账号定位。
2. 读取 `references/intent-routing.md`，先区分“要求生图”和“明确跳过确认”；只有明确表达跳过确认时才进入直接模式，语义不确定默认需要确认。
3. 读取 `references/run-state.md`，初始化或恢复任务状态；状态未允许时禁止调用图片生成后端。
4. 读取 `references/planning-output.md`，按“内容分析 → 推荐方案 → 封面确认”的精简格式输出规划；内部保存的分析文件不等于用户确认。
5. 读取 `references/image-generation.md`，确定图片流程、独立审查和质量边界。
6. 如果主题属于狗狗账号 IP，读取 `references/ip-routing.md`，按动漫 IP 或真实写实模式选择素材；不删除或混用两类 IP 资产。
7. 默认路径先展示规划并停止等待用户确认；直接模式可以继续，但必须展示采用的规划摘要和标题。
8. 只创建并生成封面 Prompt；把第一版封面展示给用户，同时把同一张图交给独立审查 Agent。封面未 PASS 前，不得创建第 2 张及之后的最终 Prompt，也不得生成知识卡。
9. 只有封面审查 PASS 后，才输出精简的知识卡摘要方案并解锁后续 Prompt；知识卡批量生成后先在工作区展示全部成图，再逐张交给独立审查 Agent。
10. 读取 `../../third_party/baoyu-xhs-images/SKILL.md`，并按需读取其中引用的 Reference；将已确认的标题、正文、图片数量、对应参考表情和完整 Prompt 传给仓库内置的 Baoyu 模块。每个 Prompt 必须先落盘。

Baoyu 的完整 `analysis.md`、`outline.md` 和 Prompt 文件属于内部可追溯产物；用户可见的规划只按 `references/planning-output.md` 展示，不重复展开 Baoyu 的长版视觉方案。

## 边界

- 本 Skill 不直接实现图片生成后端。
- 没有正文或明确的图片主题时，不自行编造内容。
- “用户要求生图”不等于“用户允许跳过确认”；意图分层规则见 [`references/intent-routing.md`](references/intent-routing.md)。
- 默认路径必须等待用户确认；直接模式必须有当前用户消息中的明确跳过确认原文。
- 不在位图上涂改错字或替换文字；发现问题必须修改 Prompt 并重新生成。
- 独立审查只判断可见角色的生理结构：多/少耳朵、眼睛、鼻子、嘴巴、腿、爪子、尾巴，以及明显断裂、粘连、重复或残影；不审查文字、排版、遮挡、场景、IP 一致性、审美、文案事实或政策内容。
- 封面和每张知识卡最多尝试 3 次；第 3 次仍失败必须停止并陈述具体原因。
- 阶段状态见 [`references/run-state.md`](references/run-state.md)；状态锁优先于批量生成便利性。

## 规划输出

详细字段和示例见 [`references/planning-output.md`](references/planning-output.md)。
