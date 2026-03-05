# Apple OS Release RSS to Slack

通过 GitHub Actions 定时监控 [Apple Developer Releases RSS](https://developer.apple.com/news/releases/rss/releases.rss)，过滤 iOS / macOS / iPadOS / watchOS 的正式版和测试版更新，推送到 Slack。

## 功能

- 每 15 分钟自动检查 RSS 更新
- 支持手动触发（可强制推送最新 N 条）
- 关键词过滤：只推送 iOS、macOS、iPadOS、watchOS 相关条目
- 自动去重，避免重复推送

## 配置步骤

1. **创建 Slack Incoming Webhook**
   - 前往 [Slack API](https://api.slack.com/apps) 创建一个 App
   - 启用 Incoming Webhooks，选择目标频道，获取 Webhook URL

2. **Fork 或克隆本仓库**

3. **配置 Repository Secret**
   - 进入仓库 Settings > Secrets and variables > Actions
   - 添加 `SLACK_WEBHOOK_URL`，值为第 1 步获取的 Webhook URL

4. **给 Actions 写权限**
   - 进入仓库 Settings > Actions > General > Workflow permissions
   - 选择 "Read and write permissions"

5. **完成** — Actions 会按 cron 自动运行，也可在 Actions 页面手动触发

## 手动触发

在 GitHub Actions 页面点击 "Run workflow"，可选参数：

- `force`：设为 `true` 忽略去重记录，强制推送当前 RSS 中的最新条目

## 自定义过滤

编辑 `feeds.yml` 中的 `keywords` 列表，添加或移除你关心的系统名称。

## 文件说明

| 文件 | 用途 |
|------|------|
| `rss_to_slack.py` | 主脚本：拉取 RSS、过滤、推送 Slack |
| `feeds.yml` | RSS 源地址与过滤关键词配置 |
| `sent_items.json` | 已推送条目记录（自动维护） |
| `.github/workflows/rss-to-slack.yml` | GitHub Actions 工作流 |
