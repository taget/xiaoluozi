# 小落子

一个 Python 进程上的个人助手工作台。对外只有 `xiaoluozi.handle(message, channel="web") -> Reply`。网页和微信通道都只调用这个入口，共用一份最近对话和同一份 Hindsight 记忆。

`Reply.text` 是给对方看的回复，末尾另起一行写选用了哪个代理，以及这条决定的依据。`saved` 表示这一轮有没有写进记忆。`note` 只在没写进去时有一句说明。

## 回路

`Loop` 是唯一的编排者，顺序固定，不要打乱，也不要跳步：

1. 用用户的最新输入做成决策依赖，只把这一句交给 laya。
2. 调用 laya：决定用哪个代理，并明确用户意图。不执行代理。结果进入该 `agent_id` 自己的决策队列。和队列里最新一条的代理、依据、意图都相同，则不入队。laya 失败时，沿用队列里最新一条，也不入队；队列是空的，这一轮拒绝。每个代理一条，默认 10 条，构造 `Loop` 时用 `decision_limit` 改。哪一条满了，就只把那一条写成一份记忆并清空；没满不写。
3. 按选中的代理拉取它自己的上下文记忆：本地最近对话里只取这个 `agent_id` 的 8 轮，Hindsight 召回带上 `agent:{agent_id}`。再把用户的话、这份记忆和意图交给该代理。代理再请求一次大模型。
4. 写入：把这一轮交给记忆端口，标签带这个 `agent_id`。意图记在认知里。同时追加到本地最近对话，并记下是哪个代理。

失败时的行为也是固定的：

- 路由结果不是合法选择、选了 `none`，或选出了未知代理：回退到 `.env` 里的默认代理，这一轮继续。
- 代理没返回可用回复：抛出 `ReplyError`，不写记忆。
- 空句子：`ReplyError("先写一句话。")`，不写记忆。
- laya 没有给出可识别的意图：代理照常处理，记忆里的认知写成 `没有识别出意图。`。
- 记忆写入失败或未配置：回复照常返回，`saved=False`，`note` 为 `这一轮没有存进记忆。`。本地最近对话追加失败也不影响回复。
- `.env` 里没有 `TYPESAFE_API_KEY`：抛出 `ModelNotConfigured`。不要编一条假回复，也不要发网络请求。
- 问答模型没配好（缺 `LLM_API_KEY`、`LLM_BASE_URL` 或 `LLM_MODEL_NAME`）：代理抛出 `ModelNotConfigured`，回路收成 `ReplyError`，不写记忆，不发网络请求。

laya 只做这一次决策：选代理，并明确意图。发给它的 `state` 里，用户问题是决策依赖，也就是这一轮的原话；当前上下文在这里是空的。代理选定之后才取它自己的上下文记忆，交给 `_revise_context`。这一步现在原样返回，以后改某个代理的记忆只改这里。做决定前打出「决策依赖」，交给代理前打出「上下文记忆」。召回失败或没有记忆时，这一轮继续；该代理没有记忆，才写「没有可用的上下文。」。没有合适的代理时用默认代理，意图仍然传给它。只要启用了代理，就会询问 laya。

记忆已配置时，代理调用大模型经 `hindsight_litellm.wrap_openai`。`chat` 和 `qa` 共用这一份客户端。laya 这次路由不走包装器，避免改写上面的 `state`。回路最后仍把这一轮写成一份文档，`document_id` 就是 `turn_id`，正文包含通道、用户的话、路由决定、模型回复和认知。不要把同一轮拆成多个共用 `document_id` 的条目，后写入的会盖掉先写入的。地址和 bank id 只从 `.env` 读取，不安装 Hindsight 服务。本地最近对话写在 `data/history.json`，和 Hindsight 是两份东西。

## 代理

代理放在 `xiaoluozi/agents/`。每个代理有 `id`、`description` 和 `handle(message, context, intent) -> str`。

`handle` 不选代理，不调用工具，不写记忆。它用自己的系统提示词，把上下文、意图和用户的话交给大模型，只调用一次。

`chat` 是日常对话，也是默认代理。`qa` 回答需要说明或解释的问题。启用哪些代理由 `.env` 的 `ENABLED_AGENTS` 决定，默认用哪一个由 `DEFAULT_AGENT` 决定。代码里没有的 id 不能启用。两个代理用同一份问答模型。

Skill 放在 `xiaoluozi/skills/<name>/SKILL.md`，按 Agent Skills 组织。frontmatter 里有 `name` 和 `description`，`name` 与目录名一致，只用小写字母、数字和连字符。正文是给模型的说明。`references/`、`scripts/`、`assets/` 留在目录里，不放进这次请求。

代理用 `skill_ids` 点名它支持哪些 skill。装配时先读每个 skill 的 `name` 和 `description`。被点名的 skill，在这一轮把正文按声明顺序接到该代理的系统提示词后面。没有点名的代理，系统提示词保持原样。

文件对不上、正文是空的，或点了未知 skill：装配失败，中文说明是哪一个。不请求模型，不写记忆。

加一个专职代理时：

1. 新类放进 `xiaoluozi/agents/`，中文 `description` 写清它接什么句子。
2. 在 `xiaoluozi/wiring.py` 的代理清单里登记，并把 `skills.load(新代理.skill_ids)` 交给它。`.env` 的 `ENABLED_AGENTS` 写上它的 id 之后，路由器才会把它交给 laya。
3. 补测试。启用了代理时，调用顺序是：laya 决策，然后该代理请求大模型。

## 边界

- 密钥只放在项目根目录的 `.env`，不写进仓库、测试或页面。`Settings.load` 只读这个文件，不读进程环境变量。微信扫码登录后的 bot token 写在 gitignore 的 `data/weixin/account.json`，只在 `WEIXIN_ENABLED=true` 且 `.env` 里没有 `WEIXIN_BOT_TOKEN` 时读取。相关键见 `README.md`。
- Jev 客户端 POST systemone，请求体是 `model`、`state`、`questions`。问题只有 `choice`、`score`、`noul`。不发 `messages`。
- 代理用 `.env` 里的 `LLM_API_KEY`、`LLM_BASE_URL`、`LLM_MODEL_NAME`。地址如果已经以 `/chat/completions` 结尾，客户端会先去掉这段再追加。请求体是 `model` 和 `messages`，第一条是该代理自己的系统提示词。
- 回路在选定代理后拼该代理的上下文：本地最近对话里这个 `agent_id` 的 8 轮，再 `memory.recall(message, agent_id)`。最后调用 `memory.retain_turn`，标签含 `agent:{agent_id}`。代理这次调用上的注入和写入由 `wrap_openai` 完成。Hindsight 的地址和 bank id 从 `.env` 传给包装器。
- 页面只呈现回复、是否写入，以及失败说明。选用哪个代理和决策依据写在回复末尾，不另开一块，也不展开认知原文。网页和微信的回合都出现在同一条对话里，微信来的那一句标成「微信」。
- `app` 关闭了 OpenAPI 文档。服务绑定 `0.0.0.0:8741`。微信通道在 `WEIXIN_ENABLED=true` 且有 token 时，由进程里的后台线程长轮询，收到文本后调用同一个 `handle`，`channel` 为 `weixin`。

## 开发

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m xiaoluozi
```

单元测试用 `tests/fakes.py` 里的假模型和假记忆，不访问 Venus 或 Hindsight。需要 Python 3.11+。

用户能看见的句子用中文，短、具体，并说明这一轮实际发生了什么。
