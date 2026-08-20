# SocialDataX 数据源

Creator OS 通过 `scripts/xhs_provider.py` 选择数据源：有可用 Apify Key 时默认使用 Apify 上的 SocialDataX Actor；未配置 Key 时使用已安装、已登录的本机 MediaCrawler。用户明确指定提供方时优先遵从。

若 Apify 已配置但套餐、Actor 或网络请求失败，不能自动跳到 MediaCrawler；必须说明原因并由用户明确选择。MediaCrawler 细则见 `../skills/xhs-research/references/local-mediacrawler.md`。

## 两个操作

- `search_notes`：按关键词抓取公开笔记，默认 15 条；测试或用户明确要求更多样本时，可按要求扩大 `limit`。Compare 首轮对象不足时，必须先提示用户，只有用户明确确认后才扩大到 25 条。
- `get_note_detail`：读取指定笔记的标题、作者、正文/摘要、发布日期、笔记类型和公开互动数据。

## 链接规则

- 支持完整的 `xiaohongshu.com` 链接和 `xhslink.com` 短链接。
- `rednote.com` 输入会在请求前转换为 `www.xiaohongshu.com` 长链；`/discovery/item/<note_id>` 会转换为 `/explore/<note_id>`，并保留全部查询参数。
- `xhslink.com` 先按原短链请求一次；如果请求失败或没有返回详情，适配器会跟随短链跳转，转换为小红书长链后再请求一次。
- 两次都失败时，错误信息会同时保留短链请求和长链兜底的失败原因；不能把失败当作 0 条真实结果。
- 不删除 `xsec_token`、`xsec_source` 或其他 provider 参数。
- 抓取结果里的原始 URL 直接作为用户看到的笔记超链接，不能自行拼接或改成 canonical URL。

## API Key

运行：

```bash
python3 scripts/xhs_provider.py status
```

适配器按以下顺序读取，不显示密钥内容：

1. 当前进程环境变量 `APIFY_API_TOKEN`；
2. Skill 目录下被 Git 忽略的 `.env.local`；
3. macOS Keychain 项目 `xhs-creator-os/apify-api-token`。

`scripts/setup_apify_key.py` 用于首次写入或迁移 Keychain。`.env.local` 权限保持为 `600`，不得复制到报告、提示词、聊天记录或 Git。

SocialDataX Actor 需要 Apify 付费计划。遇到免费套餐限制时，必须明确报告为访问阻断，不能把返回的 0 条当作真实搜索结果。

## 缓存与去重

- 笔记详情缓存在被 Git 忽略的 `data/note-detail-cache/`。
- 同一笔记 ID 或同一 URL 哈希已有非空结果时，直接读取缓存，不重复发起付费请求。
- 只有用户明确要求刷新，才使用 `--refresh`。
- 研究原始记录保持不变，报告从规范化数据生成。
- 缓存命中和新请求 API 返回的详情都进入同一套仿写输出协议；缓存只影响是否发起详情请求，不影响元信息、标题/钩子/CTA 选项、轻度/深度选项或正文格式。
- Compare 的简化策略不维护复杂分页或 Actor 侧排除 ID；首轮 15 条结果不足时，先按实际对象数量输出并提示用户，只有用户明确确认扩大搜索后才用更大的 `limit`（例如 25）重新搜索，并在本地按 `note_id`、原始 URL 或标题+作者做基础去重。
- `runs/latest/research.json` 是当前运行结果；不要把一次运行结果误认为所有查询条件的长期缓存。研究记录仍应通过 `scripts/store.py` 导入，Compare 只基于本次实际可用结果生成。

## 标准字段

```text
note_id, url, title, body, author_id, author_name, author_url,
published_at, note_type, content_level, detail_status, captured_at,
query, source, likes, saves, comments, shares, raw
```

第三方互动数据是抓取时快照。缺失值写“未知”，不猜测、不补零。

- `content_level`：`card`（搜索卡片）、`summary`（搜索摘要）、`detail`（详情请求结果）。
- `detail_status`：`not_requested`、`success`、`unavailable`。只有 `detail + success` 才能作为正文级内容的优先来源。
