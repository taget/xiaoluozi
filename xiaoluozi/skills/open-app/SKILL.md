---
name: open-app
description: 给用户一个打开本地应用的入口。只准备入口，不在后台打开。
allowed-tools:
  - Open
---

# 打开本地应用

用户明确要打开本机应用时，调用 `Open`。`app` 用配置名单里的 id，例如 `chrome`、`iterm2`、`wxwork`。名单以外的应用不要编一个入口。

工具返回的入口原样写进回复。不要说应用已经打开。用户还没点之前，它只是一个入口。
