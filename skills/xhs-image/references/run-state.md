# 生图任务状态锁

Skill 文档是行为规范，任务状态是执行闸门。每次生图任务都应在任务目录保存一个 `run-state.yaml`，并在每次生成前检查它。

## 状态模板

```yaml
version: 1
image_request: true
scope: series
confirmation_mode: required
asset_mode: anime-ip
phase: planning
cover_status: not_started
card_plan_status: locked
card_generation_status: locked
review_status: not_started
attempts:
  cover: 0
  cards: {}
```

## 合法状态

```text
planning
  ↓
waiting_for_confirmation
  ↓
cover_generating
  ↓
cover_review_pending
  ├─ cover_passed
  └─ cover_failed / cover_blocked
       ↓
card_plan_ready
  ↓
cards_generating
  ↓
cards_workspace_preview
  ↓
cards_review_pending
  ├─ completed
  └─ partial_failure
```

直接模式可以从 `planning` 进入 `cover_generating`，但不能跳过 `cover_review_pending` 和 `cover_passed`。

## 硬性锁

- `phase: planning` 或 `waiting_for_confirmation`：禁止调用图片生成后端。
- `cover_status: not_started`：禁止创建或生成知识卡图片。
- `cover_status: review_pending`：禁止创建第 2 张及之后的最终 Prompt，禁止批量生成知识卡。
- 只有 `cover_status: passed`：才允许创建知识卡 Prompt，并以通过的封面作为系列锚点。
- 知识卡生成完成后必须先设置 `card_generation_status: workspace_preview`，再进入逐张审查。
- 任何图片 `FAIL` 只锁定该图片，不回滚已经 `PASS` 的图片。
- 第 3 次仍 `FAIL` 时设置 `partial_failure` 或 `cover_blocked`，并保留失败样本、最后 Prompt 和失败原因。

## 确认记录

默认路径必须记录用户确认原文或等价回复，例如：

```yaml
confirmation:
  status: confirmed
  source: user_message
  text: "标题 2，按这个方案生成"
```

直接路径必须记录触发直接模式的原文；没有原文就不能设置 `bypassed_explicitly`。
