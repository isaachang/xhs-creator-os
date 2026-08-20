# 小红书 Creator OS

> 给 Codex 使用的小红书内容工作流：调研 → 仿写 → 多对象对比 → 生图。
>
> 默认使用 Apify → SocialDataX；没有 API Key 时，可配置本机 MediaCrawler 作为备用数据路径。

Creator OS 是内容研究与创作辅助工具，不会自动发布、点赞、评论、关注或私信。

---

## 它能做什么

| 能力 | 你可以怎么说 | 会得到什么 |
| --- | --- | --- |
| 调研 | `调研广州宠物友好酒店` | 原始链接、标题、作者、发布时间、互动快照、详情状态 |
| 单篇仿写 | `仿写这个链接：<笔记链接>` | 原笔记信息、标题/钩子/CTA 选项与可发布正文 |
| 多对象对比 | `对比天河 5 家宠物友好酒店` | 数据来源、评分表、五星正文与补充核验项 |
| 博主拆解 | `抓这个博主收藏最高的 5 篇：<主页链接>` | 本次扫描范围内按收藏快照排序的 Top N 笔记详情 |
| 生图 | `根据这篇正文做小红书知识卡` | 使用内置图片卡模板，输出封面优先的系列配图 |

## 工作流

```text
用户需求
  │
  ├─ 调研 ───────────► xhs-research ─┬─ Apify → SocialDataX
  │                                  └─ 本机 MediaCrawler
  │
  ├─ 链接仿写 ───────► xhs-rewrite ───► 优先复用本地详情缓存
  │
  ├─ 多对象对比 ─────► xhs-compare ───► 调研、归类、评分、发布正文
  │
  └─ 生图 / 审图 ────► xhs-image ─────► 内置 Baoyu 图片卡模板 → Codex imagegen
```

---

## 第一次使用：先完成 Media 配置

Media 不需要 API Key。它是无 Apify Key 时的本机抓取路径，也能用于本机备用验证。

下载仓库并在 Codex 中打开该目录后，直接发送：

```text
帮我完成 xhs-creator-os 的首次初始化：优先配置 MediaCrawler，检查登录态，并做一次低风险调研测试。
```

Codex 会先执行：

```bash
python3 scripts/setup_mediacrawler.py --check
```

如果 Media 未就绪，经你同意后执行：

```bash
python3 scripts/setup_mediacrawler.py --install
```

初始化脚本会：

1. 下载指定版本的上游 MediaCrawler；
2. 应用 Creator OS 的兼容适配；
3. 创建独立 Python 环境；
4. 安装依赖与 Playwright 浏览器运行环境；
5. 输出下一步登录操作。

### 作为用户，你只需要做什么

| 场景 | 你需要做的事 |
| --- | --- |
| 首次安装 | 同意 Codex 下载第三方代码和本机依赖 |
| 首次登录 / 登录过期 | 使用手机扫一次小红书或 Rednote 二维码 |
| 平台要求验证码或滑块 | 完成一次临时可见验证 |
| 日常使用 | 直接发送调研需求或笔记链接 |

正常抓取使用独立登录目录并在后台运行：不会接管你的日常 Chrome，也不需要手动开启 Chrome CDP 或配置 Google Cloud。

> 登录失效或平台安全校验时，Codex 会展示一次临时二维码或提示可见验证；这不是每次抓取都会发生的步骤。

---

## 配置账号定位

复制模板：

```bash
cp profile/account.example.yaml profile/account.yaml
```

然后编辑 `profile/account.yaml`，填写：

- 账号定位与目标读者；
- 内容支柱；
- 语气与表达方式；
- 真实性边界；
- 默认调研设置。

`profile/account.yaml` 是个人配置，不应上传到公开仓库。

## 可选：配置 Apify

如果你有 Apify Key，可以使用 SocialDataX 获得更稳定、结构更完整的云端数据。

复制本地配置模板：

```bash
cp .env.example .env.local
```

在 `.env.local` 中填写：

```bash
APIFY_API_TOKEN=你的_Apify_API_Key
```

默认 Actor 已经配置为：

```text
socialdatax~socialdatax-xhs-data-api
```

不需要手动选择 Actor。只有想换其他 Actor 时，才填写：

```bash
APIFY_XHS_ACTOR=owner~actor-name
```

检查当前状态：

```bash
python3 scripts/xhs_provider.py status
```

数据源优先级：

```text
有可用 Apify Key → Apify → SocialDataX
没有 Apify Key → 已配置的本机 MediaCrawler
```

如果 Apify 已配置但套餐、Actor 或网络调用失败，系统不会静默改用 Media；会说明原因并等待你明确选择。

---

## 日常使用

在 Codex 中调用：

```text
$xhs-creator-os
```

然后直接说人话：

| 你说 | 系统路径 |
| --- | --- |
| `调研广州宠物友好公园` | 搜索候选 → 按当前意图筛选 → 读取所选详情 → 返回正式样本 |
| `仿写这个链接：<链接>` | 先查详情缓存，不足时读取公开详情，再生成仿写 |
| `对比广州 5 家狗狗公园` | 优先复用缓存；不足时调研；输出评分表与发布正文 |
| `抓这个博主收藏最高的 5 篇：<主页链接>` | 扫描作者卡片 → 按收藏快照排序 → 只读 Top N 详情 |
| `根据正文做 6 张知识卡` | 路由到独立小红书生图流程 |

---

## 生图模板：已内置，无需另装 Baoyu

本仓库已携带完整的 `baoyu-xhs-images` 单个 Skill。打开项目后，Codex 会自动发现它；不需要再单独下载 Baoyu 全套 Skills。

它提供：

- 12 种视觉风格、8 种信息版式和 3 组配色；
- 内容拆页、封面优先、封面作为后续卡片视觉锚点；
- 完整 Prompt 先落盘、失败卡片单独重生成、审图规则；
- 使用当前 Codex 可用的图片生成后端，优先走 `imagegen`。

你自己的角色或狗狗参考图**不会随仓库提供**。如需保持账号 IP，请自行放入：

```text
assets/ip/refs/                 # 动漫/插画 IP 参考图
assets/ip/real-dog/refs/        # 已授权的真实狗狗参考图
```

默认使用：

```text
$xhs-creator-os
根据这篇正文做 6 张小红书知识卡
```

`xhs-image` 负责读取你的账号与 IP 路由规则；内置的 `baoyu-xhs-images` 负责视觉方案、拆页、Prompt 和生图工作流。第三方来源与许可见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

---

## 数据与输出原则

- 调研样本保留上游给出的原始笔记 URL、作者与互动数据快照；
- 互动数据不是实时数据，缺失字段显示“未知”，不补零；
- `detail + success` 才是正文级来源；搜索卡片不能被当作完整正文；
- 本机 Media 搜索会先采集候选，再结合本轮用户意图动态筛选，避免把异地或不相关内容直接返回；
- 仿写与 Compare 优先复用本地详情缓存，减少重复抓取与 API 消耗；
- 发布正文使用纯文本复制框，标题不超过 20 字，标题、正文、结尾和标签合计不超过 1000 字；
- 费用、政策、准入限制等不确定信息放在正文外的“补充核验”中，而不是写成调研报告口吻。

本地数据目录：

```text
data/note-detail-cache/   # 已读取笔记详情缓存
data/creator-os.sqlite3  # 结构化历史数据
runs/                    # 每次调研、对比、仿写的运行产物
```

这些目录默认被 Git 忽略。

---

## 项目结构

```text
xhs-creator-os/
├── SKILL.md                         # 总路由与运行规则
├── README.md                        # 用户安装与使用说明
├── profile/
│   ├── account.example.yaml          # 账号定位模板
│   └── account.yaml                  # 本地个人配置（不上传）
├── references/                       # 数据源、证据、文案共用规则
├── skills/
│   ├── xhs-research/                 # 调研与作者抓取
│   ├── xhs-rewrite/                  # 单篇链接仿写
│   ├── xhs-compare/                  # 多对象比较
│   └── xhs-image/                    # 生图适配层
├── .agents/skills/
│   └── baoyu-xhs-images/              # 内置图片卡模板、视觉预设与生成流程
├── assets/ip/refs/                    # 用户自行添加的 IP 参考图（不含个人素材）
├── scripts/
│   ├── setup_mediacrawler.py         # Media 安装与体检
│   ├── xhs_provider.py               # Apify / Media 路由
│   └── validate_copy.py              # 发布文案字数校验
└── third_party/mediacrawler/         # 上游适配补丁与许可证说明
```

---

## 限制与合规

- 只读取公开内容，不自动执行发布、互动或账号操作；
- MediaCrawler 仅适合个人学习、研究与低频测试，请遵守其上游许可证和平台规则；
- Media 可能受登录状态、验证码和站点风控影响；
- 作者“收藏最高”仅代表本次扫描范围内的公开互动快照，不代表全历史绝对排名；
- 上游抓取到的正文与互动数据不应被表述为你的亲身体验。

## 隐私

不要上传以下内容：

```text
.env.local
profile/account.yaml
.baoyu-skills/
data/
runs/
MediaCrawler/browser_data/
API Key、Cookie、二维码、订单信息、联系方式
```
