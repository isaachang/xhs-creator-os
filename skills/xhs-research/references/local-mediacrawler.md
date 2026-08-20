# 本机 MediaCrawler 候选采集与动态筛选（可选降级路径）

当 Apify 未配置、且本机 MediaCrawler 可用时，`--source auto` 选择此路径；用户也可以明确要求“本机抓取 / MediaCrawler”。如果 Apify 已配置但调用失败，不能静默切换，必须让用户明确选择本机路径。

它使用用户登录的小红书浏览器会话，适合作为低频本机验证；首次启动后会根据专用 Profile 的会话域名、实际页面跳转和扫码后的最终页面自动识别 `xiaohongshu.com` 或 `rednote.com`。只保存站点名称，不保存或输出 Cookie；后续复用同一专用 Profile，不要求用户手动选择站点。原上游仓库为非商业学习许可，不作为公开分发 Skill 的默认数据源。

## 两段式动态筛选

不要把搜索页前 15 张卡片直接当成调研结果。MediaCrawler 只负责采集；Creator OS 根据本轮用户意图做筛选。执行：

1. 抓取 30 条候选搜索卡片。Creator OS 默认只搜索图文 / `image`，用户可改为视频 / `video` 或全部 / `all`。
2. Agent 从本轮用户请求动态提取地点、对象、主题、排除条件与比较目标；逐条标记“直接相关 / 可参考 / 噪声”。不得套用固定城市、商场、宠物或账号词表。
3. Agent 选择最多 12 条“直接相关”或标题不足以判断的候选，使用其原始 URL 读取详情；不抓评论或媒体资源。
4. Agent 基于卡片与详情生成最终 `research.selection.json`，再生成最多 15 条正式样本；不足 15 条时如实返回实际数量，不用噪声补足。

例如“广州天河宠物友好商场”应同时判断天河、宠物、商场；“广州宠物友好公园”应判断广州、宠物、公园，不能再要求“天河”或“商场”。异地或对象不符的候选必须在本轮判断中标为噪声，并保留判断理由。

本机执行时必须显式启用筛选，例如：

```bash
python3 scripts/xhs_provider.py search "关键词" --source media --limit 15 \
  --sort-type general --content-type image \
  --output "运行目录/research.json"
```

该命令先写出 `research.candidates.json`。Agent 完成动态筛选后，再批量读取所选详情：

```bash
python3 scripts/xhs_provider.py details "笔记 URL 1" "笔记 URL 2" --source media \
  --output "运行目录/research.details.json"
python3 scripts/finalize_mediacrawler_research.py \
  --candidates "运行目录/research.candidates.json" \
  --details "运行目录/research.details.json" \
  --selection "运行目录/research.selection.json" \
  --output "运行目录/research.json" --limit 15
```

## 记录与输出

- `research.candidates.json`：30 条候选卡片，字段与 Apify 研究结果对齐，但尚未是正式样本。
- `research.raw.json`：全部未经修改的原始候选卡片。
- `research.selection.json`：当前 Agent 对每条候选的动态纳入/排除理由与详情核验清单。
- `research.json`：最终正式样本，字段与 Apify 研究结果对齐，并附 `relevance_status`、`relevance_reasons`。
- `research.details.json`：本轮按 `research.selection.json` 选择读取的详情。
- `research.manifest.json`：实际站点（Rednote / 小红书）、内容类型、排序、数量与详情状态；不包含 Cookie。

研究窗口只展示 `research.json` 样本；头部必须注明“本机 MediaCrawler 动态筛选：候选 X 条，详情核验 Y 条，正式样本 Z 条”。用户要求查看噪声或筛选原因时，再引用 `research.selection.json`。`content_level=card` 的样本不是正文详情，不能用于深度事实判断。

Media 的搜索接口目前没有与 SocialDataX 完全等价的服务端发布时间筛选；用户指定发布时间范围时，先如实说明该限制，并在拿到详情日期后做本地筛选，不能假装平台已按时间筛好。

## 限制与停止条件

- 详情核验是为了判断相关性，不等于可以把全部正文当作发布事实；Compare 或仿写仍需遵守详情来源和证据边界。
- 登录失效、验证码、站点安全限制或详情连续失败时立即停止，保存已有候选，并明确说明未完成精筛。
- 不导出 Cookie、不显示会话值、不抓评论。
