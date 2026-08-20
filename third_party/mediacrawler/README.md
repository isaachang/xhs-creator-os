# MediaCrawler 适配说明

Creator OS 的本机 Media 路径依赖上游 [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)，并在首次初始化时应用 `creator-os-adapter.patch`。

- 上游基线提交：`d6f7c5bb906b6dac40ddf343ef9e26438a3de092`
- 本补丁增加 Creator OS 所需的统一 JSON 输出、Rednote / 小红书站点识别、二维码写入、候选卡片采集和作者 Top-N 路径。
- 不包含上游源代码、浏览器登录态、Cookie、缓存或抓取数据。
- 上游项目采用 `NON-COMMERCIAL LEARNING LICENSE 1.1`；仅限遵守其许可证与平台规则的个人学习、研究和低频测试使用。

不要手动修改补丁。运行 `python3 scripts/setup_mediacrawler.py --install` 会下载对应上游基线并应用它。
