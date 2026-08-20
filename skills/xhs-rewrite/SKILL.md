---
name: xhs-rewrite
description: 读取用户提供的小红书笔记链接，展示原笔记元信息并生成默认仿写，支持轻度仿写和深度仿写。
---

# 小红书 Rewrite 子 Skill

本 Skill 只服务于用户提供具体笔记链接后的单篇拆解和仿写。

## 读取规则

执行前读取：

- `../../references/data-sources.md`
- `../../references/evidence-boundary.md`
- `../../references/copy-format.md`
- `../../references/account-context.md`
- `references/rewrite-output.md`
- `references/rewrite-modes.md`

## 执行流程

1. 接受 `xhslink.com`、`xiaohongshu.com` 或 `rednote.com` 笔记链接。
2. 先检查本地详情缓存；已有非空结果时不重复请求，除非用户明确要求刷新。
3. 没有缓存时调用 SocialDataX `get_note_detail`；`rednote.com` 先转换为小红书长链，`xhslink.com` 先请求短链，失败后再解析并请求小红书长链。
4. 保留 SocialDataX 返回的原始 `note_url`，不删除 `xsec_token`、`xsec_source` 或其他参数。
5. 读取标题、作者、作者主页、正文/摘要、笔记类型、发布日期和公开互动数据。
6. 按 `references/rewrite-output.md` 展示元信息、5 个标题、5 个钩子、1 版默认正文和 5 个 CTA。
7. 默认正文完成后，固定提供轻度仿写和深度仿写两个后续选项。

缓存命中和 API 新请求必须进入同一套输出协议；缓存只改变是否发起详情请求，不改变返回结构、选项数量或正文格式。
