---
name: xhs-creator-os
description: 用 SocialDataX 做小红书前期调研，或读取用户提供的小红书笔记并进行仿写。支持完整样本、作者与互动数据、原始链接、详情缓存，以及轻度/深度仿写两种后续模式。
---

# 小红书调研与仿写总路由

本 Skill 负责判断用户意图、读取对应功能清单、调用共享脚本，并按统一格式返回结果。不要一次性加载所有 `references/` 文件，只读取当前路径需要的清单。

## 路由

### 调研

用户要求搜索、调研、抓取关键词、查看样本或分析一个方向时：

1. 读取 `references/research.md`。
2. 同时读取 `references/data-sources.md`，按其中的 API、链接、缓存和字段规则执行。
3. 使用 `profile/account.yaml` 理解账号方向；没有关键词时，只生成一个最直接的搜索词。
4. 调用 SocialDataX `search_notes`，完整返回所有抓取样本。

### 指定笔记仿写

用户提供 `xhslink.com`、`xiaohongshu.com` 或 `rednote.com` 笔记链接，并要求读取、拆解或仿写时：

1. 读取 `references/rewrite.md`。
2. 同时读取 `references/data-sources.md`，先检查本地详情缓存；已有非空结果时不重复请求，除非用户明确要求刷新。
3. 没有缓存时调用 SocialDataX `get_note_detail`。
4. 保留 SocialDataX 返回的原始 `note_url`，不删除 `xsec_token` 或其他参数。
5. 读取标题、作者、作者主页、正文/摘要、笔记类型、发布日期和公开互动数据。
6. 使用 `profile/account.yaml` 的账号定位生成默认仿写；用户选择轻度或深度后，再执行对应的第二轮仿写。

### 生图或审图

只有用户明确提出“生图”“图片卡片”“小红书配图”或“审图”时：

1. 读取 `references/image-generation.md`。
2. 按清单调用当前环境可用的独立图片生成 Skill。
3. 不因为用户正在调研或仿写，就自动生成图片。

## 共享上下文

- 账号定位只读取 `profile/account.yaml`，不要自动加载创作中心复盘、竞品审图、复杂选题架构或其他未被请求的模块。
- API Key 只从环境、被 Git 忽略的 `.env.local` 或 macOS Keychain 读取，绝不输出、写入报告、Prompt、聊天记录或 Git。
- 只读取公开笔记，不发布、点赞、评论、关注或绕过平台控制。
- 保留原始抓取记录，报告从规范化数据生成。
- 第三方点赞、收藏、评论、转发是抓取时快照，不代表实时数据。
- 缺失数据写“未知”，不猜测、不补零。
- 调研元数据和分析内容可以使用 Markdown；可发布正文必须使用纯文本代码框，代码框内禁止 `#`、项目符号、加粗符号或其他 Markdown 排版。
- 所有可发布正文都必须遵守 `references/rewrite.md` 的字数上限：标题不超过 20 字；标题、正文和标签合计不超过 1000 字。
- 用户提供初稿后要求优化、默认仿写、轻度仿写和深度仿写，都属于可发布正文，必须执行上述限制；原始调研样本、元信息和内部分析不套用该限制。
- 输出前使用 `scripts/validate_copy.py` 检查字数；超限时先压缩重复表达、装饰性形容词和非关键衔接，再重新检查，不能直接超限返回。

## 共享命令

检查 API 配置，不暴露密钥：

```bash
python3 scripts/xhs_api.py status
```

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
