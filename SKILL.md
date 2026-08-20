---
name: xhs-creator-os
description: 用 Apify → SocialDataX 或本机 MediaCrawler 做小红书前期调研、单篇笔记仿写或多对象对比；统一返回原始链接、作者、互动数据与详情状态。
---

# 小红书 Creator OS 总路由

本 Skill 只负责判断用户意图、加载对应子 Skill、调用共享脚本，并按统一格式返回结果。不要一次性加载所有规则，只读取当前路径需要的子 Skill 和 Reference。

## 路由

### 调研

用户要求搜索、调研、抓取关键词、查看样本或分析一个方向时，读取 `skills/xhs-research/SKILL.md`。

Research 子 Skill 需要按需加载：

- `references/data-sources.md`
- `references/evidence-boundary.md`
- `references/account-context.md`
- `skills/xhs-research/references/research-output.md`

通过 `scripts/xhs_provider.py status` 判断数据源：有可用 Apify Key 时使用 `Apify → SocialDataX`；未配置 Key 时使用本机 MediaCrawler。用户明确指定某一数据源时优先遵从。Media 路径额外读取 `skills/xhs-research/references/local-mediacrawler.md`。

若 Apify 已配置但套餐、Actor 或网络请求失败，不能静默切换到 Media；明确说明错误并提供“使用本机 MediaCrawler”的选项。

### 单篇笔记仿写

用户提供 `xhslink.com`、`xiaohongshu.com` 或 `rednote.com` 笔记链接，并要求读取、拆解或仿写时，读取 `skills/xhs-rewrite/SKILL.md`。

Rewrite 子 Skill 需要按需加载：

- `references/data-sources.md`
- `references/evidence-boundary.md`
- `references/copy-format.md`
- `references/account-context.md`
- `skills/xhs-rewrite/references/rewrite-output.md`
- `skills/xhs-rewrite/references/rewrite-modes.md`

### 多对象对比

用户要求对比多个酒店、商场、餐厅、景点或其他对象时，读取 `skills/xhs-compare/SKILL.md`。

Compare 子 Skill 优先检查本地历史 Research 和详情缓存。缓存足够时直接复用，不调用 API；缓存不足时默认第一次抓取 15 条。如果用户明确要求的对比对象数量仍未达到，先按实际对象数量生成正文，并在正文外说明缺口；只有用户明确确认后，才扩大 `limit` 到 25。仍然不足时，按实际找到的对象生成正文。

Compare 子 Skill 需要按需加载：

- `references/data-sources.md`
- `references/evidence-boundary.md`
- `references/copy-format.md`
- `references/account-context.md`
- `skills/xhs-compare/references/comparison-output.md`
- `skills/xhs-compare/references/comparison-scoring.md`

### 生图或审图

只有用户明确提出“生图”“图片卡片”“小红书配图”或“审图”时，读取 `skills/xhs-image/SKILL.md`。

`xhs-image` 是小红书流程适配层，实际图片生成继续调用独立的 `baoyu-xhs-images` Skill。不要因为用户正在调研、仿写或对比，就自动生成图片。

## 共享上下文

- 账号定位只读取 `profile/account.yaml`，并遵守 `references/account-context.md`；不要自动加载创作中心复盘、竞品审图、复杂选题架构或其他未被请求的模块。
- API Key 只从环境、被 Git 忽略的 `.env.local` 或 macOS Keychain 读取，绝不输出、写入报告、Prompt、聊天记录或 Git。
- 只读取公开笔记，不发布、点赞、评论、关注或绕过平台控制。
- 保留原始抓取记录，报告从规范化数据生成。所有抓取记录都使用统一字段：`note_id`、`url`、`title`、`body`、`author_name`、`author_url`、`published_at`、`note_type`、赞/藏/评/转、`content_level`、`detail_status`、`query`、`source`、`raw`。
- 第三方点赞、收藏、评论、转发是抓取时快照，不代表实时数据。
- 缺失数据写“未知”，不猜测、不补零。
- 调研元数据和分析内容可以使用 Markdown；可发布正文必须遵守 `references/copy-format.md`，使用纯文本代码框，代码框内禁止 `#`、项目符号、加粗符号或其他 Markdown 排版。
- 用户提供初稿后要求优化、默认仿写、轻度仿写、深度仿写或生成对比正文，都属于可发布正文，必须执行字数限制；原始调研样本、元信息和内部分析不套用该限制。
- 输出前使用 `scripts/validate_copy.py` 检查字数；超限时先压缩重复表达、装饰性形容词和非关键衔接，再重新检查，不能直接超限返回。

## 共享命令

检查数据源配置，不暴露密钥：

```bash
python3 scripts/xhs_provider.py status
```

本机 Playwright 持久化浏览器会话（首次需要用户手动登录一次）：

```bash
./.venv/bin/python scripts/xhs_browser_session.py login
./.venv/bin/python scripts/xhs_browser_session.py status
```

登录态保存在被 Git 忽略的 `data/browser-profile/`，不导出 Cookie，不写入研究记录。`status` 会在关闭后重新打开一个全新的上下文，检查首页是否仍要求登录；只有返回 `authenticated` 才算复用成功，返回 `login_required` 或 `security_blocked` 都不能继续抓取。小红书返回 `安全限制 / 300011` 时，属于站点安全阻断，不应把它误报成搜索结果为空。

搜索笔记：

```bash
python3 scripts/xhs_provider.py search "关键词" --source auto --limit 15 \
  --sort-type general --content-type image --output runs/latest/research.json
```

`content-type` 可选 `image`（默认图文）、`video`、`all`。Media 候选采集后必须由当前 Agent 动态筛选并读取所选详情，再生成正式 `research.json`；不能把候选卡片直接当最终研究结果。

读取指定笔记：

```bash
python3 scripts/xhs_provider.py detail "完整笔记 URL" --source auto --output runs/latest/note-detail.json
```
