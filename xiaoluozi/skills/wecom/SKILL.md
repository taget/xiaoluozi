---
name: wecom
description: 用本机官方 wecom-cli 操作企业微信。查联系人、文档、日程、会议、待办、邮件、微盘和消息时使用。
allowed-tools:
  - Wecom
---

# 企业微信

这是代理点名的 `wecom` 连接器，定义在 `connectors/wecom/cli.json`。用 `Wecom` 调用本机已经安装的官方 `wecom-cli`。这个工具不打开企业微信窗口。用户只要打开窗口时，告诉他这一轮不能代开。

业务调用前，进程会先看版本和授权。还没装好或还没授权时，回复就是那一句说明，不会交给你改写。不要补充自建应用，不要向用户要 `corp_id`、`agent_id` 或应用密钥，也不要自己执行 `npm install` 或 `wecom-cli auth init`。只有用户在问装好没有、授权了没有时，才单独调用 `{"action":"version"}` 或 `{"action":"auth"}`。

不知道子命令或参数时，先对品类要帮助：`{"category":"calendar","help":true}`。看完帮助再调用。品类只在这些里面：contact、calendar、meeting、todo、email、disk、media、message、doc-manage、doc、sheet、smartsheet、smartpage、pptx、identity。

调用写成 `{"category":"contact","command":["users","search"],"args":{}}`。`command` 是子命令片段，不要写 `--` 开头的参数。`args` 是交给 `--json` 的对象。需要本地文件时写绝对路径，工作目录不在项目里。

查询可以直接做。发送消息、删除、取消、修改别人的日程或文档之前，先用一句话跟用户确认，得到同意再调用。

最终回复只用姓名、标题、时间、邮箱这类可读信息。`userid`、`docid`、`chat_id` 以及其他机器标识留在工具结果里，不要写给用户。工具说没完成、没查到或没授权，就照实说，不要补一条看起来成功的结果。
