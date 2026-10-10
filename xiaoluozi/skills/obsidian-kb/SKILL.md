---
name: obsidian-kb
description: 检索个人知识库。仓库是 https://github.com/taget/obsidian 的本地检出，只读笔记、技术、工作、日记和待办。
allowed-tools:
  - Vault
---

# 个人知识库

仓库地址是 https://github.com/taget/obsidian。读的是 `OBSIDIAN_VAULT_PATH` 指向的本地检出。只检索。不要创建、修改、删除笔记，也不要 commit、push 或 pull。

笔记在 `superme/` 下：

- `00-索引/MOC.md` 是知识地图。不确定笔记在哪一区时先看它。
- `Persona 定义.md` 是人物设定。
- `10-技术/` 技术笔记，标签以 `#tech/` 开头。
- `20-工作/` 工作记录，标签以 `#work/` 开头。
- `30-工具与平台/` 工具和平台，标签以 `#tool/` 开头。
- `40-生活/` 生活，标签以 `#life/` 开头。
- `50-daily/` 每日记录，文件名是 `YYYY-MM-DD.md`，标签 `#daily`。
- `60-todo/` 待办，标签以 `#status/` 开头。

用 `Vault`：

- `map` 读取知识地图。
- `search` 的 `query` 用笔记里可能出现的词，不要把整句问题当关键词。几个词都要出现才算命中。可以多次搜索。
- `read` 的 `path` 用相对路径，例如 `superme/10-技术/某笔记.md`。

回答里写出来源路径。检索结果说没有这篇笔记，或没有找到，就告诉对方知识库里没有，不要补一篇看起来像的内容。
