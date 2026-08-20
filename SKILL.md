---
name: xhs-creator-os
description: 用 Apify → SocialDataX 做小红书前期调研、单篇笔记仿写或多对象对比；支持完整样本、作者与互动数据、原始链接、详情缓存、对比正文，以及轻度/深度仿写两种后续模式。
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

用户明确要求“本机抓取 / MediaCrawler”，或 Apify 未配置且用户明确选择本机方案时，额外读取 `skills/xhs-research/references/local-mediacrawler.md`。它是显式降级路径，不能替换默认 Apify 路由。

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
- 保留原始抓取记录，报告从规范化数据生成。
- 第三方点赞、收藏、评论、转发是抓取时快照，不代表实时数据。
- 缺失数据写“未知”，不猜测、不补零。
- 调研元数据和分析内容可以使用 Markdown；可发布正文必须遵守 `references/copy-format.md`，使用纯文本代码框，代码框内禁止 `#`、项目符号、加粗符号或其他 Markdown 排版。
- 用户提供初稿后要求优化、默认仿写、轻度仿写、深度仿写或生成对比正文，都属于可发布正文，必须执行字数限制；原始调研样本、元信息和内部分析不套用该限制。
- 输出前使用 `scripts/validate_copy.py` 检查字数；超限时先压缩重复表达、装饰性形容词和非关键衔接，再重新检查，不能直接超限返回。

## 共享命令

检查 API 配置，不暴露密钥：

```bash
python3 scripts/xhs_api.py status
```

本机 Playwright 持久化浏览器会话（首次需要用户手动登录一次）：

```bash
./.venv/bin/python scripts/xhs_browser_session.py login
./.venv/bin/python scripts/xhs_browser_session.py status
```

登录态保存在被 Git 忽略的 `data/browser-profile/`，不导出 Cookie，不写入研究记录。`status` 会在关闭后重新打开一个全新的上下文，检查首页是否仍要求登录；只有返回 `authenticated` 才算复用成功，返回 `login_required` 或 `security_blocked` 都不能继续抓取。小红书返回 `安全限制 / 300011` 时，属于站点安全阻断，不应把它误报成搜索结果为空。

搜索笔记：

```bash
python3 scripts/xhs_api.py search "关键词" --source apify --limit 15 --output runs/latest/research.json
python3 scripts/store.py import runs/latest/research.json --kind research --query "关键词" --source xhs-api
python3 scripts/trend_report.py --days 7 --output runs/latest/trends.md
```

读取指定笔记：

```bash
python3 scripts/xhs_api.py detail "完整笔记 URL" --source apify --output runs/latest/note-detail.json
```
