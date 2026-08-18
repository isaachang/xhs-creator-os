# SocialDataX 数据源

本 Skill 的唯一外部数据源是 Apify 上的 SocialDataX Actor，用于小红书关键词搜索和指定笔记详情读取。

## 两个操作

- `search_notes`：按关键词抓取公开笔记，默认 15 条；测试或用户明确要求时可抓取 20 条。
- `get_note_detail`：读取指定笔记的标题、作者、正文/摘要、发布日期、笔记类型和公开互动数据。

## 链接规则

- 支持完整的 `xiaohongshu.com` 链接和 `xhslink.com` 短链接。
- `rednote.com` 链接可能被 Actor 拒绝；适配器只在请求时转换输入主机，输出仍保留 SocialDataX 返回的原始 `note_url`。
- 不删除 `xsec_token`、`xsec_source` 或其他 provider 参数。
- 抓取结果里的原始 URL 直接作为用户看到的笔记超链接，不能自行拼接或改成 canonical URL。

## API Key

运行：

```bash
python3 scripts/xhs_api.py status
```

适配器按以下顺序读取，不显示密钥内容：

1. 当前进程环境变量 `APIFY_API_TOKEN`；
2. Skill 目录下被 Git 忽略的 `.env.local`；
3. macOS Keychain 项目 `xhs-creator-os/apify-api-token`。

`scripts/setup_apify_key.py` 用于隐藏输入并写入被 Git 忽略的 `.env.local`。`.env.local` 权限保持为 `600`，不得复制到报告、提示词、聊天记录或 Git。macOS Keychain 也可作为适配器的读取来源，但不应把密钥写进仓库。

SocialDataX Actor 需要 Apify 付费计划。遇到免费套餐限制时，必须明确报告为访问阻断，不能把返回的 0 条当作真实搜索结果。

## 缓存与去重

- 笔记详情缓存在被 Git 忽略的 `data/note-detail-cache/`。
- 同一笔记 ID 或同一 URL 哈希已有非空结果时，直接读取缓存，不重复发起付费请求。
- 只有用户明确要求刷新，才使用 `--refresh`。
- 研究原始记录保持不变，报告从规范化数据生成。

## 标准字段

```text
note_id, url, title, body, author_id, author_name, author_url,
published_at, captured_at, query, source, likes, saves, comments, shares, raw
```

第三方互动数据是抓取时快照。缺失值写“未知”，不猜测、不补零。
