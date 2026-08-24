# 生图意图路由

本文件解决一个关键区别：用户想要生图，不等于用户允许跳过规划确认。

## 路由字段

每次进入 `xhs-image`，先在内部得到以下字段，并写入任务状态：

```yaml
image_request: true
scope: cover | series
confirmation_mode: required | bypassed_explicitly
asset_mode: anime-ip | real-photo
phase: planning
```

字段含义：

- `image_request`：本次是否真的要求生成图片。
- `scope`：只生成封面，还是生成完整图片卡系列。用户说“生成一套”“知识卡片”通常是 `series`，但不代表跳过确认。
- `confirmation_mode`：是否明确授权跳过用户确认。
- `asset_mode`：动漫 IP 或真实写实资产；未指定时遵守 `ip-routing.md` 的默认路由。
- `phase`：当前生成阶段，必须遵守 `run-state.md` 的状态锁。

## 默认确认路径

以下表达只说明用户想生成，不说明用户想跳过确认：

- “根据这篇正文生成一套知识卡”
- “帮我做小红书配图”
- “把这段内容做成 6 张图”
- “帮我生成封面和知识卡”
- “生一套图看看”

统一路由为：

```yaml
image_request: true
scope: series
confirmation_mode: required
phase: planning
```

必须先展示规划，并在默认路径停止等待用户确认。内部生成 `analysis.md` 或 `outline.md` 不等于用户已经确认。

## 明确直接生成路径

只有用户明确表达“跳过确认”的意思，才设置 `confirmation_mode: bypassed_explicitly`。包括：

- “直接生成一套”
- “直接出图”
- “不用确认方案，直接生成”
- “跳过规划，按默认方案生成”
- “按默认方案直接生成，不用问我”
- `--yes`

判断原则：语义等价必须同时包含“立即执行”和“跳过确认”两个含义。单独出现“生成”“一套”“默认”“开始做”不能触发直接模式。

直接模式可以跳过用户等待，但仍然必须：

1. 展示采用的规划摘要和标题。
2. 只生成封面作为第一组任务。
3. 展示封面，并输出独立审查过程。
4. 封面通过后才解锁知识卡。
5. 批量生成知识卡后展示全部图片，再逐张审查。

## 语义不确定时

如果无法判断用户是否明确跳过确认，默认使用 `confirmation_mode: required`，不要猜测用户授权了直接生成。

## 典型判断

| 用户表达 | 路由 | 是否等待确认 |
| --- | --- | --- |
| 根据正文生成 6 张知识卡 | `series + required` | 是 |
| 帮我做一套小红书配图 | `series + required` | 是 |
| 直接生成一套，不用确认 | `series + bypassed_explicitly` | 否，但仍展示过程 |
| 只生成一个封面 | `cover + required` | 是 |
| 直接出封面，不用问我 | `cover + bypassed_explicitly` | 否，但仍审查 |
