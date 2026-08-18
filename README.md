# XHS Creator OS

> 一个可适配不同账号的小红书内容运营 Skill：调研、仿写、图片生成与持续优化。

![Research](https://img.shields.io/badge/Research-SocialDataX-7c3aed)
![Rewrite](https://img.shields.io/badge/Rewrite-Structured-0ea5e9)
![License](https://img.shields.io/badge/License-MIT-green)

## 它解决什么问题？

把分散的小红书内容工作串成一条可复用流程：

```text
账号定位 → 方向调研 → 选题提炼 → 笔记仿写 → 图片生成 → 数据复盘 → 持续优化
```

当前 Skill 默认包含两条主路径：

- **调研**：通过 Apify → SocialDataX 搜索公开笔记，完整返回标题、作者、互动数据和原始链接。
- **仿写**：读取用户提供的笔记链接，检查缓存后读取正文信息，按账号定位生成默认、轻度或深度仿写。

图片生成是可选能力，需要在你的 Agent 环境中另外配置一个可用的图片生成 Skill 或后端；本项目负责路由、账号 IP 适配和生成规则。

## 快速开始

### 1. 安装 Skill

把本目录放到 Agent 能扫描的 Skill 目录，例如：

```text
<project>/.agents/skills/xhs-creator-os/
```

或者在当前项目中直接加载本目录的 `SKILL.md`。

### 2. 配置 Apify API Key

复制示例文件：

```bash
cp .env.example .env.local
```

然后编辑 `.env.local`：

```env
APIFY_API_TOKEN=你的_Apify_API_Key
```

也可以使用内置脚本隐藏输入：

```bash
python3 scripts/setup_apify_key.py
```

检查配置时只显示状态，不会显示 Key：

```bash
python3 scripts/xhs_api.py status
```

`.env.local` 已被 `.gitignore` 忽略，严禁提交到 GitHub。

### 3. 配置账号定位

复制：

```bash
cp profile/account.example.yaml profile/account.yaml
```

然后填写：

```yaml
account:
  name: "你的账号名称"
  handle: "你的账号主页或账号标识"

positioning:
  identity: "你是谁，服务什么人"
  audience:
    - "核心受众"
  promise: "你为受众解决什么问题"
  pillars:
    - "内容支柱一"
    - "内容支柱二"
```

账号定位文件只在本机使用，不要提交真实账号策略或私人资料。

### 4. 配置账号 IP（可选）

如果账号有固定人物、宠物、吉祥物或视觉角色：

- 把参考图放到 `assets/ip/refs/`
- 在 `references/ip-adaptation.md` 写清楚角色特征、适用场景和负面约束
- 在图片生成请求中启用 IP 适配

没有 IP 时可以跳过这一步，图片生成仍可使用通用风格。

### 5. 配置图片生成后端（可选）

本项目不绑定唯一图片生成供应商。请在当前 Agent 环境中安装一个可用的图片生成 Skill 或后端，并按照该后端自己的配置方式设置：

- 默认图片模型或后端
- 图片保存目录
- 参考图传入方式
- 批量生成数量

`references/image-generation.md` 是本项目的统一路由入口，不要求某个固定供应商名称。

## 使用方式

在 Agent 中加载 `SKILL.md` 后，可以直接说：

```text
帮我调研：广州天河宠物友好商场
```

```text
帮我仿写：https://www.xiaohongshu.com/explore/...
```

```text
根据这篇正文生成一组小红书图片卡片
```

## 常用命令

```bash
# 检查 API 状态
python3 scripts/xhs_api.py status

# 搜索笔记
python3 scripts/xhs_api.py search "关键词" --source apify --limit 15 --output runs/latest/research.json

# 读取指定笔记
python3 scripts/xhs_api.py detail "完整笔记 URL" --source apify --output runs/latest/note-detail.json
```

## 输出规则

- 调研默认返回 15 条完整样本，测试时可返回 20 条。
- 每条样本保留原始链接、标题、作者和公开互动数据。
- 笔记正文、默认仿写和优化稿：标题不超过 20 字，标题 + 正文 + 标签不超过 1000 字。
- 相同笔记详情优先读取本地缓存，避免重复请求。
- 只读取公开内容，不自动发布、点赞、评论或关注。

## 安全说明

不要提交以下内容：

```text
.env.local
profile/account.yaml
data/
runs/
个人账号资料
私人 IP 原图
```

## 目录说明

```text
SKILL.md                         # 总路由
references/research.md           # 调研清单
references/rewrite.md            # 仿写清单
references/data-sources.md       # API、缓存和链接规则
references/image-generation.md   # 图片生成路由
profile/account.example.yaml     # 账号定位模板
scripts/                         # API 和数据处理脚本
tests/                           # 脱敏测试
```

## License

MIT
