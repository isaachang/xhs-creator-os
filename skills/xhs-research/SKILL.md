---
name: xhs-research
description: 通过 Apify → SocialDataX 搜索公开小红书笔记，完整返回样本、作者、原始链接和互动数据，用于前期调研。
---

# 小红书 Research 子 Skill

本 Skill 只服务于关键词调研，不直接把调研结果改写成可发布正文。

## 读取规则

执行前读取：

- `../../references/data-sources.md`
- `../../references/evidence-boundary.md`
- `../../references/account-context.md`
- `references/research-output.md`

读取 `profile/account.yaml` 理解账号定位；API 配置、缓存、原始 URL 和字段规则以共享 Reference 为准。

## 默认参数

- 数据源：`Apify → SocialDataX`
- 默认结果：15 条
- 测试或用户明确要求更多时，按要求提高 `limit`；Compare 的扩大搜索由 Compare 子 Skill 控制，必须在首轮 15 条结果后获得用户明确确认，不能自动扩大到 25 条。
- 默认排序：综合。
- 默认笔记类型：全部。
- 默认发布时间：不限。
- 用户没有关键词时，只生成一个最直接的搜索词。

## 执行流程

1. 运行 `python3 scripts/xhs_api.py status`，不暴露 API Key。
2. 调用 SocialDataX `search_notes`。
3. 保存当前运行结果到 `runs/latest/research.json` 或用户指定的运行路径。
4. 使用 `scripts/store.py` 导入研究记录。
5. 根据 `references/research-output.md` 完整返回样本。

## 输出边界

- 必须列出本次抓取到的全部样本，不因相关性弱而静默删除。
- 每条样本显示原始标题、SocialDataX 返回的原始 URL、作者名称、作者主页（如果有）、发布日期、笔记类型和赞/藏/评/转。
- 缺失互动数据写“未知”，不能补成 0。
- 相关性、噪声和待确认内容只用 `⚠️` 提示。
- 不自动跳转到官网、Booking 或其他网页做第二轮核验，除非用户明确要求。
- 先返回完整资料，再提供用户可以选择的后续分析方向。
