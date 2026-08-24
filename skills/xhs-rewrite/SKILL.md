---
name: xhs-rewrite
description: 读取用户提供的小红书笔记链接，展示原笔记元信息并生成默认仿写，支持轻度仿写和深度仿写。
---

# 小红书 Rewrite 子 Skill

本 Skill 只服务于用户提供具体笔记链接后的单篇拆解和仿写。

## 读取规则

执行前读取：

- `../../references/data-sources.md`
- `../../references/cache-routing.md`
- `../../references/evidence-boundary.md`
- `../../references/copy-format.md`
- `references/rewrite-output.md`
- `references/rewrite-modes.md`

先只读取 `../../profile/account.yaml` 判断账号匹配；仅在判断为“匹配”，或用户明确要求按其账号改写时，再读取 `../../references/account-context.md` 参与生成。

## 执行流程

1. 接受 `xhslink.com`、`xiaohongshu.com` 或 `rednote.com` 笔记链接。
2. 先按 `../../references/cache-routing.md` 检查本地详情缓存；只有相同 `note_id` 或等价 URL 的非空详情才可复用，除非用户明确要求刷新。
3. 没有缓存时调用 `scripts/xhs_provider.py detail --source auto`；有可用 Apify Key 时使用 SocialDataX，否则使用本机 MediaCrawler 的详情路径。
4. 保留本次提供方返回的原始 `note_url`，不删除 `xsec_token`、`xsec_source` 或其他参数。
5. 读取标题、作者、作者主页、正文/摘要、笔记类型、发布日期和公开互动数据；只有 `detail + success` 才视为可用于正文改写的原文内容。
6. 在生成前做一次轻量账号匹配判断：只有核心主题、目标受众或使用场景明确落入账号内容支柱时才为“匹配”。宽泛词面重合不算匹配；该判断不写入详情缓存。
7. 用户仅要求“仿写”时：匹配则按账号定位仿写；不匹配或不确定则按原笔记主题仿写，并在元信息中说明实际路径。用户明确要求“不要结合账号”时，始终按原主题仿写。
8. 用户明确要求“按我的账号改写”但原笔记与账号不匹配时，检查是否已有用户提供或调研得到的账号主题素材。没有时先做一句简短澄清：该笔记只能提供结构和表达参考，不能支撑账号主题的事实正文；请用户提供目标主题/素材，或明确要求先做调研。不得直接生成跨主题正文。
9. 按 `references/rewrite-output.md` 展示元信息、5 个标题、5 个钩子、1 版默认正文和 5 个 CTA；正文必须使用 `text` 纯文本代码框。
10. 默认正文完成后，固定提供轻度仿写和深度仿写两个后续选项。

缓存命中和新请求必须进入同一套输出协议；缓存只改变是否发起详情请求，不改变返回结构、选项数量或正文格式。卡片或摘要不足时必须先补读单篇详情。
