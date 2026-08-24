---
name: xhs-creator-os
description: 用 Apify → SocialDataX 或本机 MediaCrawler 做小红书前期调研、单篇笔记仿写或多对象对比；统一返回原始链接、作者、互动数据与详情状态。
---

# 小红书 Creator OS 总路由

本 Skill 只负责判断用户意图、加载对应子 Skill、调用共享脚本，并按统一格式返回结果。不要一次性加载所有规则，只读取当前路径需要的子 Skill 和 Reference。

## 路由

### 调研

用户要求搜索、调研、抓取关键词、查看样本、抓取博主公开笔记、对标账号或分析一个方向时，读取 `skills/xhs-research/SKILL.md`。

Research 子 Skill 需要按需加载：

- `references/data-sources.md`
- `references/cache-routing.md`
- `references/evidence-boundary.md`
- `references/account-context.md`
- `skills/xhs-research/references/research-output.md`

用户首次使用、账号定位尚未配置或意图不完整时，再读取 `references/user-guidance.md`。账号定位不是调研、仿写或抓取博主的前置条件。

通过 `scripts/xhs_provider.py status` 判断数据源：有可用 Apify Key 时使用 `Apify → SocialDataX`；未配置 Key 时使用本机 MediaCrawler。用户明确指定某一数据源时优先遵从。Media 路径额外读取 `skills/xhs-research/references/local-mediacrawler.md`。

若 Apify 已配置但套餐、Actor 或网络请求失败，不能静默切换到 Media；明确说明错误并提供“使用本机 MediaCrawler”的选项。

### 单篇笔记仿写

用户提供 `xhslink.com`、`xiaohongshu.com` 或 `rednote.com` 笔记链接，并要求读取、拆解或仿写时，读取 `skills/xhs-rewrite/SKILL.md`。

Rewrite 子 Skill 需要按需加载：

- `references/data-sources.md`
- `references/cache-routing.md`
- `references/evidence-boundary.md`
- `references/copy-format.md`
- `skills/xhs-rewrite/references/rewrite-output.md`
- `skills/xhs-rewrite/references/rewrite-modes.md`

Rewrite 先仅读取 `profile/account.yaml` 判断原笔记是否匹配账号；只有判断为匹配，或用户明确要求“按我的账号改写”时，才加载 `references/account-context.md` 参与生成。用户仅提供链接并说“仿写”时，默认保留原笔记主题，不因账号定位自动换赛道。

### 正文创作或初稿优化

用户要求“根据调研写一篇”“把这些资料写成笔记”“优化我的初稿”或其他直接生成小红书正文的请求时，先确认当前对话、缓存或用户输入是否已有足够的事实素材。素材足够时直接读取 `references/copy-format.md`，按统一可发布正文结构生成；素材不足时先进入调研，只能在完整来源样本返回后再写正文。不要为这种常规创作额外创建子 Skill 或临时输出格式。

### 多对象对比

用户要求对比多个酒店、商场、餐厅、景点或其他对象时，读取 `skills/xhs-compare/SKILL.md`。

Compare 子 Skill 优先检查本地历史 Research 和详情缓存。缓存足够时直接复用，不调用 API；缓存不足时默认第一次抓取 15 条。如果用户明确要求的对比对象数量仍未达到，先按实际对象数量生成正文，并在正文外说明缺口；只有用户明确确认后，才扩大 `limit` 到 25。仍然不足时，按实际找到的对象生成正文。

Compare 子 Skill 需要按需加载：

- `references/data-sources.md`
- `references/cache-routing.md`
- `references/evidence-boundary.md`
- `references/copy-format.md`
- `references/account-context.md`
- `skills/xhs-compare/references/comparison-output.md`
- `skills/xhs-compare/references/comparison-scoring.md`

### 生图或审图

只有用户明确提出“生图”“图片卡片”“小红书配图”或“审图”时，读取 `skills/xhs-image/SKILL.md`。

`xhs-image` 是小红书流程适配层。实际图片生成读取仓库内置的 `third_party/baoyu-xhs-images` 模块；该模块不是 Creator OS 的独立用户入口。不要因为用户正在调研、仿写或对比，就自动生成图片。

## 共享上下文

- 账号定位只读取 `profile/account.yaml`，并遵守 `references/account-context.md`；它是 Research 的关键词兜底、生图的视觉参考，以及匹配 Rewrite 的写作参考，不是单篇仿写的强制换题材指令。不要自动加载创作中心复盘、竞品审图、复杂选题架构或其他未被请求的模块。
- API Key 只从环境、被 Git 忽略的 `.env.local` 或 macOS Keychain 读取，绝不输出、写入报告、Prompt、聊天记录或 Git。
- 所有 Media 数据调用先遵守 `references/cache-routing.md`：先检查本地正式 Research、详情缓存或作者结果，再决定是否检查登录与抓取。只有结构化条件完全兼容的缓存可以直接复用；部分相似只可辅助补搜，不得直接替代本轮结果。
- 只读取公开笔记，不发布、点赞、评论、关注或绕过平台控制。
- 保留原始抓取记录，报告从规范化数据生成。所有抓取记录都使用统一字段：`note_id`、`url`、`title`、`body`、`author_name`、`author_url`、`published_at`、`note_type`、赞/藏/评/转、`content_level`、`detail_status`、`query`、`source`、`raw`。
- 第三方点赞、收藏、评论、转发是抓取时快照，不代表实时数据。
- 缺失数据写“未知”，不猜测、不补零。
- 调研元数据和分析内容可以使用 Markdown；可发布正文必须遵守 `references/copy-format.md`，使用纯文本代码框，代码框内禁止 `#`、项目符号、加粗符号或其他 Markdown 排版。
- 用户提供初稿后要求优化、默认仿写、轻度仿写、深度仿写或生成对比正文，都属于可发布正文，必须执行字数限制；原始调研样本、元信息和内部分析不套用该限制。
- 只要本次输出包含可发布正文，都必须遵守 `references/copy-format.md` 的内容包检查：有来源时展示实际标题链接、作者链接和互动快照；固定给出 5 个标题、5 个钩子、推荐组合、一个可一键复制的 `text` 正文代码框和 5 个 CTA。Compare 可以使用多个来源样本替代单篇来源信息，并且不输出轻度/深度仿写选项。
- 输出前使用 `scripts/validate_copy.py` 检查字数；超限时先压缩重复表达、装饰性形容词和非关键衔接，再重新检查，不能直接超限返回。

## 用户可见输出协议

按本次实际动作选择格式，而不是按用户措辞临时造格式：

- **任何数据请求**（Apify API、Media 搜索、作者主页、单篇详情、缓存读取）都先按 `skills/xhs-research/references/research-output.md` 返回任务头部和完整来源样本。来源后才可以追加调研速览、对标拆解或定位草案。
- **任何可发布小红书正文**（仿写、Compare、根据调研写新稿、优化用户初稿）都按 `references/copy-format.md` 返回 5 个标题、5 个钩子、推荐组合、一个 `text` 正文代码框和 5 个 CTA。有来源时先展示真实来源元信息；没有来源时不伪造。
- **组合任务**只顺序组合上述两种结构。例如 Compare 是“来源样本 → 评分分析 → 可发布正文”；对标账号定位是“来源样本 → 内容画像 → 定位草案”，只有用户继续要求写正文才附加可发布正文结构。
- 用户可见的过程提示保持简短，只说明正在执行的阶段和下一步，不展示内部推理或技术细节；完成后最多给 3 个与本轮结果直接相关的“💡下一步建议”。

## 首次初始化

当用户首次安装后首次发起任何需要公开数据的任务，先运行 `python3 scripts/setup_mediacrawler.py --check`。Media 是无 Apify Key 时的首选本机数据路径；不要把未适配的上游 MediaCrawler 误判为已就绪。

若未安装，作为用户已发起的数据任务的正常执行步骤，自动运行 `python3 scripts/setup_mediacrawler.py --install`，不在聊天里额外询问“是否安装”。该命令会下载上游项目、应用 Creator OS 适配补丁并安装本机依赖；它不读取 API Key 或 Cookie。若操作系统要求授权，清楚说明正在申请的权限与用途后等待系统授权。

安装完成后先运行后台 `media-auth`。若它明确提示未登录、未完成可用验证，或本轮实际请求被平台以未验证会话拒绝，直接启动一次可见初始化：

```bash
python3 scripts/xhs_provider.py media-auth --media-browser visible
```

过程提示只保留简短状态，例如“正在配置本机 MediaCrawler…”、“登录窗口已打开，请扫码登录；扫码后我会自动继续。”；不要要求用户复制命令或再次确认。用户只需在 MediaCrawler 原生二维码小窗中扫码。扫码成功后小窗自动关闭，Codex 自动完成一次低频、非评论、非媒体的连接冒烟验证并恢复原任务。若 macOS 显示浏览器存储授权，提示“系统需要浏览器存储授权，请完成后继续。”不要在首次配置阶段自动抓取评论、媒体文件或大批量详情。

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

MediaCrawler 使用独立、被 Git 忽略的 Chromium Profile，不连接用户日常 Chrome。国内小红书与海外 Rednote 的 Profile、站点标记和可用验证状态分别保存，互不共享。正常本机抓取连接同一个隐藏的专用 Chromium，并复用唯一工作页；search、detail 和作者抓取退出时只释放连接、将工作页回到空白页，不会关闭会话或累计打开笔记标签。后台任务不得自动切换到可见窗口或显示二维码；但用户已发起公开数据任务且会话明确不可用时，Codex 直接运行一次可见 `media-auth` 初始化。二维码由 MediaCrawler 原生小窗显示，扫码后必须通过一次低频真实搜索验证才会保存为可复用会话：

```bash
python3 scripts/xhs_provider.py media-auth --media-browser visible
```

用户要求抓取指定作者的收藏 Top-N 时，先扫描作者笔记卡片的互动快照，再按收藏排序，只读取 Top-N 的正文详情；不能把所有笔记详情都读取一遍：

```bash
python3 scripts/xhs_provider.py creator "作者主页完整 URL" --top 5 --scan-limit 120 \
  --output runs/latest/creator-top.json
```

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
