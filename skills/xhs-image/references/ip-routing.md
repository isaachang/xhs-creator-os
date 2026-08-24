# 狗狗账号 IP 路由

当主题属于带狗旅行、日常注意、饮食、西高地、行为训练，或账号定位中的狗狗内容时读取。

## 模式选择

| 用户意图 | 模式 | 参考资产 |
| --- | --- | --- |
| 未指定，或继续使用原有动漫角色 | `anime-ip` | `assets/ip/refs/` |
| 明确要求真实写实、真实照片感，或提供并确认真实狗狗参考图 | `real-photo` | `assets/ip/real-dog/refs/` |

两种模式不得混用。真实写实模式只把真实狗狗参考图用作身份参考；背景、地点、光线、动作和表情根据当前正文重新设计。

## 动漫 IP 资产

资产索引见 `assets/ip/refs/manifest.yaml`。其中 `style-anchor.png` 是全局风格锚点，表情图按内容语义选择。每张图只选择与该卡片最匹配的一张表情参考，不要同时传入全部表情图：

| 内容情绪/场景 | 参考图 |
| --- | --- |
| 感动、温暖、被帮助 | `expression-moved.png` |
| 吃瓜、围观、事实核对 | `expression-gossip.png` |
| 疲劳、休息、作息、长途出行 | `expression-sleepy.png` |
| 反常识、风险、突发提醒 | `expression-surprised.png` |
| 警惕、注意、安全提醒 | `expression-alert.png` |
| 无语、无奈、出乎意料 | `expression-speechless.png` |
| 撒娇、求助、轻松互动 | `expression-coy.png` |
| 日常、互动、轻松技巧、结尾 CTA | `expression-playful.png` |
| 害羞、尴尬、小心翼翼 | `expression-shy.png` |
| 饮食、想吃、食物诱惑 | `expression-hungry.png` |
| 期待、等待、预告、好奇 | `expression-expectant.png` |
| 禁忌、错误做法、避坑警告 | `expression-angry.png` |
| 踩坑、焦虑、被拒、注意事项 | `expression-aggrieved.png` |
| 成功、做对了、结果展示 | `expression-proud.png` |
| 疑惑、不确定、误区 | `expression-confused.png` |
| 伤心、失落、遗憾、不舒服 | `expression-sad.png` |
| 俏皮、小技巧、轻松收尾 | `expression-wink.png` |

## 调用规则

1. 先由 `xhs-image` 按 `references/planning-output.md` 输出正文分析和封面确认；再读取 `third_party/baoyu-xhs-images` 执行已确认的生成方案。
2. 每张完整 Prompt 必须在生成前保存到 `prompts/NN-*.md`。
3. 第 1 张使用与封面标题/主题匹配的表情图或确认过的真实狗狗身份参考；动漫风格可同时参考 `style-anchor.png` 的风格特征，但不能把全部表情图传入后端。
4. 第 1 张必须经过独立审查 Agent PASS 后，后续卡片才能使用该成图作为系列锚点。
5. 小红书默认 3:4；尺寸变化不改变狗狗角色设定。
6. 生理结构错误、重复/缺失肢体或明显肢体粘连必须写新 Prompt 并重新生成，禁止在位图上修补；文字、排版和场景不属于独立生理结构审查。

## 角色边界

- 同一只白色西高地：白色粗糙蓬松毛发、直立三角耳、黑色鼻子、深色眼睛。
- 保留参考图的蜡笔/油画棒手绘质感、深蓝黑色粗轮廓和温暖纸张肌理。
- 表情和动作服务信息，不遮挡标题、步骤或关键数字。
- 用户没有提供的真实经历不得画成纪实现场，只能作为建议、示意或信息卡。
