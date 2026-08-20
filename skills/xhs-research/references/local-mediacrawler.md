# 本机 MediaCrawler 候选采集与动态筛选（可选降级路径）

仅当用户明确要求“本机抓取 / MediaCrawler”，或 Apify 未配置且用户明确选择本机方案时使用。不得把它静默接入 `--source auto`。

它使用用户登录的小红书浏览器会话，适合作为低频本机验证；首次启动后会根据专用 Profile 的会话域名、实际页面跳转和扫码后的最终页面自动识别 `xiaohongshu.com` 或 `rednote.com`。只保存站点名称，不保存或输出 Cookie；后续复用同一专用 Profile，不要求用户手动选择站点。原上游仓库为非商业学习许可，不作为公开分发 Skill 的默认数据源。

## 两段式动态筛选

不要把搜索页前 15 张卡片直接当成调研结果。MediaCrawler 只负责采集；Creator OS 根据本轮用户意图做筛选。执行：

1. 抓取 30 条候选搜索卡片。
2. Agent 从本轮用户请求动态提取地点、对象、主题、排除条件与比较目标；逐条标记“直接相关 / 可参考 / 噪声”。不得套用固定城市、商场、宠物或账号词表。
3. Agent 选择最多 12 条“直接相关”或标题不足以判断的候选，使用其原始 URL 读取详情；不抓评论或媒体资源。
4. Agent 基于卡片与详情生成最终 `research.selection.json`，再生成最多 15 条正式样本；不足 15 条时如实返回实际数量，不用噪声补足。

例如“广州天河宠物友好商场”应同时判断天河、宠物、商场；“广州宠物友好公园”应判断广州、宠物、公园，不能再要求“天河”或“商场”。异地或对象不符的候选必须在本轮判断中标为噪声，并保留判断理由。

本机执行时必须显式启用筛选，例如：

```bash
uv run main.py --platform xhs --type search --keywords "关键词" \
  --crawler_max_notes_count 15 --research_screening yes \
  --research_candidate_count 30 \
  --fetch_details no --get_comment no --creator_os_output "运行目录/research.candidates.json"
```

## 记录与输出

- `research.candidates.json`：30 条候选卡片，字段与 Apify 研究结果对齐，但尚未是正式样本。
- `research.raw.json`：全部未经修改的原始候选卡片。
- `research.selection.json`：当前 Agent 对每条候选的动态纳入/排除理由与详情核验清单。
- `research.json`：最终正式样本，字段与 Apify 研究结果对齐，并附 `relevance_status`、`relevance_reasons`。
- `research.details.json`：本轮按 `research.selection.json` 选择读取的详情。

研究窗口只展示 `research.json` 样本；头部必须注明“本机 MediaCrawler 动态筛选：候选 X 条，详情核验 Y 条，正式样本 Z 条”。用户要求查看噪声或筛选原因时，再引用 `research.selection.json`。

## 限制与停止条件

- 详情核验是为了判断相关性，不等于可以把全部正文当作发布事实；Compare 或仿写仍需遵守详情来源和证据边界。
- 登录失效、验证码、站点安全限制或详情连续失败时立即停止，保存已有候选，并明确说明未完成精筛。
- 不导出 Cookie、不显示会话值、不抓评论。
