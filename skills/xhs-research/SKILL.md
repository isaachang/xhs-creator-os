---
name: xhs-research
description: 通过 Apify → SocialDataX 或本机 MediaCrawler 搜索公开小红书笔记，统一返回样本、作者、原始链接、互动数据与详情状态。
---

# 小红书 Research 子 Skill

本 Skill 只服务于关键词调研，不直接把调研结果改写成可发布正文。

## 读取规则

执行前读取：

- `../../references/data-sources.md`
- `../../references/evidence-boundary.md`
- `../../references/account-context.md`
- `references/research-output.md`

当 `scripts/xhs_provider.py status` 选择 Media，或用户明确要求本机 MediaCrawler 时，额外读取 `references/local-mediacrawler.md`。

读取 `profile/account.yaml` 理解账号定位；API 配置、缓存、原始 URL 和字段规则以共享 Reference 为准。

## 默认参数

- 数据源：`auto`（有可用 Apify Key 时为 `Apify → SocialDataX`；无 Key 时为本机 MediaCrawler）
- 默认结果：15 条
- 测试或用户明确要求更多时，按要求提高 `limit`；Compare 的扩大搜索由 Compare 子 Skill 控制，必须在首轮 15 条结果后获得用户明确确认，不能自动扩大到 25 条。
- 默认排序：综合。
- 默认笔记类型：图文 / `image`；用户可指定视频 / `video` 或全部 / `all`。
- 默认发布时间：不限。
- 用户没有关键词时，只生成一个最直接的搜索词。
- Apify 已配置但调用失败时不静默改用 Media，必须明确说明后等待用户选择；只有“未配置 Apify”才自动走 Media。

## 执行流程

1. 运行 `python3 scripts/xhs_provider.py status`，不暴露 API Key 或 Cookie。
2. 调用 `scripts/xhs_provider.py search`，并传递关键词、数量、排序、内容类型与发布时间参数。
3. Apify 返回后直接得到正式 `research.json`；Media 先得到 30 条候选卡片。
4. Media 路径由当前 Agent 按用户意图动态标记候选；随后使用 `scripts/xhs_provider.py details <选中 URL...>` 读取最多 12 条选中详情，执行 `scripts/finalize_mediacrawler_research.py` 生成正式 `research.json`；该脚本会写入统一详情缓存和研究索引。详情阶段沿用候选运行清单中的同一提供方，不能无意切换来源。
5. 根据 `references/research-output.md` 完整返回正式样本。

本机 MediaCrawler 路径：抓取 30 条候选卡片 → 由当前 Agent 根据用户本轮需求动态标记相关性 → 最多读取 12 条已选或待确认候选详情 → 生成最多 15 条正式样本。不得使用固定城市、账号或品类词表替代本轮意图判断；细则与许可边界见 `references/local-mediacrawler.md`。

## 输出边界

- 正式样本必须完整列出，不因相关性弱而静默删除；仅 Media 的候选层允许先筛选，候选与排除理由保存在本地。
- 本机精筛模式必须透明说明候选数量、详情核验数量、正式样本数量；原始候选和排除理由保存在本地，不静默丢弃。正式样本不足 15 条时按实际数量返回。
- 每条样本显示提供方返回的原始标题和 URL、作者名称、作者主页（如果有）、发布日期、笔记类型和赞/藏/评/转。
- `content_level=card`、`summary`、`detail` 分别表示搜索卡片、搜索摘要和详情请求结果。用户要求读取正文、深度拆解、仿写或细节型 Compare 时，优先复用 `detail` 缓存；没有详情才读取单篇详情。
- 缺失互动数据写“未知”，不能补成 0。
- 相关性、噪声和待确认内容只用 `⚠️` 提示。
- 不自动跳转到官网、Booking 或其他网页做第二轮核验，除非用户明确要求。
- 先返回完整资料，再提供用户可以选择的后续分析方向。
