---
name: xhs-image
description: 将已确认的小红书标题、正文、钩子和账号 IP 交给独立的 baoyu-xhs-images Skill，生成小红书图片卡片或执行审图。
---

# 小红书生图适配层

本 Skill 只负责小红书内容到图片生成 Skill 的衔接，不复制或替代独立的 `baoyu-xhs-images`。

## 触发条件

只有用户明确要求“生图”“图片卡片”“小红书配图”或“审图”时使用。调研、仿写和 Compare 不自动触发本 Skill。

## 执行规则

1. 读取 `../../references/account-context.md`，理解账号定位。
2. 读取 `references/image-generation.md`，确定图片流程和质量边界。
3. 如果主题属于狗狗账号 IP，读取 `references/ip-routing.md`，按动漫 IP 或真实写实模式选择素材；不删除或混用现有 IP 资产。
4. 将已确认的标题、钩子、正文、CTA、图片数量和视觉要求传给独立的 `baoyu-xhs-images` Skill。
5. 遵守封面先生成、通过检查后再生成后续卡片、Prompt 先落盘、失败卡片单独重生成等规则。

## 边界

- 本 Skill 不直接实现图片生成后端。
- 不因为正文生成完成就自动生成图片。
- 不在位图上涂改错字或替换文字。
