# MediaCrawler 适配说明

Creator OS 的本机 Media 路径依赖上游 [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)，并在首次初始化时应用 `creator-os-adapter.patch`。上游运行副本会安装到 `third_party/mediacrawler/runtime/`：该目录包含依赖和专用浏览器登录态，始终被 Git 忽略。

- 上游基线提交：`d6f7c5bb906b6dac40ddf343ef9e26438a3de092`
- 本补丁增加 Creator OS 所需的统一 JSON 输出、Rednote / 小红书站点识别、本地二维码小窗、候选卡片采集和作者 Top-N 路径。Creator OS 在二维码登录后按最终站点将本机 Profile 隔离为国内小红书或海外 Rednote，并以一次低频搜索验证会话可用性。由于 Rednote 可能拒绝无头会话，正常后台任务使用离屏的专用 CDP Chrome（1×1、屏幕外），不显示或控制用户日常 Chrome；后台任务从不自动弹二维码。
- 仓库只包含适配补丁与说明；`runtime/` 是本机自动下载的上游代码、依赖、浏览器登录态、Cookie、缓存与抓取数据的容器，绝不提交或分享。
- 上游项目采用 `NON-COMMERCIAL LEARNING LICENSE 1.1`；仅限遵守其许可证与平台规则的个人学习、研究和低频测试使用。

不要手动修改补丁。运行 `python3 scripts/setup_mediacrawler.py --install` 会下载对应上游基线并应用它。
