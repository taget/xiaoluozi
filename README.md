# 小落子

一个 Python 进程上的个人助手工作台。你写一句话，进程里的回路先路由、再让兜底代理回复、然后抽出一条短认知，并把这一轮写入外部记忆。页面显示回复。已启用的代理列在对话左侧，输入框左侧也可以选「自动」「团队」或某个代理。选中某个代理后记在这个页面上，之后每一句都带上这个 `@id`，不再问 laya，直到改成「自动」或「团队」。选「团队」时，laya 只选主代理，主代理再委派只读代理；会发消息或改数据的代理不会被自动调用。网页这一轮的调用链单独放在对话右侧，下一句发出后这条链收起。

用户的一句话进来后，先拉取上下文和已启用的代理，再让 laya 决定用哪个代理，并明确意图。然后把这句话、上下文和意图交给那个代理，由它请求一次大模型。没有合适的代理时用默认代理，意图照样传过去。`chat` 是日常对话，也是默认代理。找不到专职代理时，它的系统提示词后面会接上 laya 的返回。它默认加载 `search`，可以调用 `Search`。`CHAT_SKILLS` 可以改它加载的 skill。要给打开本地应用的入口，把 `open-app` 加进这个名单，应用写在 `xiaoluozi/open_apps.toml`。`qa` 回答需要说明或解释的问题。`cvm` 负责 CVM 运营，加载 `yunxiao-ops`。`kb` 检索个人知识库，加载 `obsidian-kb`，只读 https://github.com/taget/obsidian 的本地检出，不改仓库，也不写入记忆。`migrate` 负责 CVM 迁移，`vstation` 负责 vstation 排障。它们用 knot-sdk 把这句话交给各自的 Knot 端点，不请求本地问答模型。再加一个这样的代理，在 `.env` 写 `KNOT_AGENT_<ID>` 和 `KNOT_AGENT_<ID>_DESCRIPTION` 即可。`cvm_low_level` 用同一份 `KNOT_API_TOKEN`，通过 Knot MCP 检索 CVM 底层知识库，只检索，不写入记忆。查到的文档链接附在回复末尾。`perf_gap` 处理云主机相对物理机吞吐下降约 20%–40% 的专项排障，加载 `perf-gap`。材料不够时写明现在不能认定根因，并给出只读的 `collect_perf.sh`。不改配置，不跑压测。`wxwork` 处理企业微信里的联系人、文档、日程、会议、待办、邮件、微盘和消息。它点名连接器 `wecom`，定义在 `xiaoluozi/connectors/wecom/cli.json`，调用本机官方 `wecom-cli`。没装好或还没授权时，不请求问答模型，直接回复安装或 `wecom-cli auth init` 的说明。这不是自建应用，不要 `corp_id`、`agent_id` 或应用密钥。打开企业微信窗口仍是 `open_apps.toml` 里的 `wxwork` 入口。代理实现在代码里，启用名单在 `.env`。它们不自己写记忆。`cvm` 在模型返回 `Bash` 工具调用时会执行命令，再把结果交回模型。`kb` 在模型返回 `Vault` 时只检索笔记。新代理要在命令里用环境变量时，在类上写 `env_keys`，装配时只把这些键从 `.env` 带进这次命令。

网页和微信是两条通道，共用最近对话，也共用同一份 Hindsight 记忆。微信走和 OpenClaw `openclaw-weixin` 一样的 iLink 机器人接口：长轮询收文本，再把回复发回去。

```python
from xiaoluozi import handle

reply = handle("今天要不要出门")
reply.text   # 给对方看的回复，末尾带选用的代理和决策依据
reply.saved  # 这一轮有没有写进记忆
reply.note   # 没写进去时的一句说明，写进去了就是 None
```

## 本地运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m xiaoluozi
```

`knot-sdk` 不在公共 PyPI。上面这条如果找不到它，改用腾讯镜像再装一次：

```bash
pip install -e ".[dev]" -i https://mirrors.tencent.com/pypi/simple --trusted-host mirrors.tencent.com
```

服务绑定 `0.0.0.0:8741`。浏览器打开 [http://127.0.0.1:8741](http://127.0.0.1:8741)。

也可以：

```bash
uvicorn xiaoluozi.app:app --host 0.0.0.0 --port 8741
```

## 配置

密钥和地址写在项目根目录的 `.env`，不要写进仓库。进程环境变量不会被读取。

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `TYPESAFE_API_KEY` | Jev 的密钥 | 无。缺了页面会说明模型还没配好，不会编一条假回复 |
| `TYPESAFE_BASE_URL` | systemone 地址。已经以 `/systemone` 结尾就原样 POST，否则发到 `{BASE_URL}/v1/systemone` | `http://v2.open.venus.oa.com/llmproxy` |
| `TYPESAFE_DEFAULT_MODEL` | 路由、回复、认知三次调用用的模型 | `jev-1.13.0` |
| `HINDSIGHT_BASE_URL` | [Hindsight](https://github.com/vectorize-io/hindsight) 服务地址 | 无 |
| `HINDSIGHT_BANK_ID` | 唯一的记忆库 | 无 |
| `LLM_API_KEY` | 问答代理的密钥 | 无。缺了被选中时会说明问答模型还没配好，不会编一条假回复 |
| `LLM_BASE_URL` | 问答的 chat completions 地址。已经以 `/chat/completions` 结尾就先去掉这段，再由客户端追加 | 无 |
| `LLM_MODEL_NAME` | 问答用的模型 | 无 |
| `LAYA_MODEL` | 只负责选择代理的模型 | `laya` |
| `ENABLED_AGENTS` | 启用的代理 id，逗号分隔。实现必须在代码里，或按下面的 Knot 端点配好 | `chat,qa,cvm,kb,migrate,vstation,cvm_low_level,wxwork,perf_gap` |
| `DEFAULT_AGENT` | 没有合适代理时使用的代理 | `chat` |
| `CHAT_SKILLS` | `chat` 加载的 skill，逗号分隔。没写时是 `search`。留空则不加载 | `search` |
| `WEIXIN_ENABLED` | 是否接收微信消息 | `false` |
| `WEIXIN_BOT_TOKEN` | 微信 iLink bot token。留空时，在通道已启用的前提下改读 `data/weixin/account.json` | 无 |
| `WEIXIN_BASE_URL` | iLink 接口地址。登录文件里有 `baseUrl` 且这里没写时，用登录文件里的地址 | `https://ilinkai.weixin.qq.com` |
| `WEIXIN_ACCOUNT_ID` | 同步游标文件名 | `default` |
| `YUNXIAO_SECRET_ID` | 云霄 API 标识。`cvm` 的 `env_keys` 会把它带进这次 Bash | 无 |
| `YUNXIAO_SECRET_KEY` | 云霄 API 密钥。只放在 `.env` | 无 |
| `YUNXIAO_API_URL` | 云霄 API 地址。执行命令时带进去 | 无 |
| `OBSIDIAN_VAULT_PATH` | 个人知识库的本地检出。仓库是 https://github.com/taget/obsidian 。`kb` 只在这个目录里检索 | 无 |
| `KNOT_API_TOKEN` | Knot 个人令牌。`migrate`、`vstation`、`cvm_low_level` 共用。留空时不发请求 | 无 |
| `KNOT_API_URL` | `migrate` 的 agui 地址。`KNOT_AGENT_MIGRATE` 有值时用后者 | `http://knot.woa.com/apigw/api/v1/agents/agui/687fb0de01614c5b84ba495919c5ff02` |
| `KNOT_AGENT_<ID>` | 某个 Knot 代理的 agui 地址。已有 id 用它改端点；新 id 再配 `KNOT_AGENT_<ID>_DESCRIPTION` 就会多一个代理 | 见 `.env.example` |
| `KNOT_AGENT_VSTATION` | vstation 排障的 agui 地址 | `http://knot.woa.com/apigw/api/v1/agents/agui/dcfd1be40f2d430a98f689b9e96bd6c8` |
| `TOOL_MAX_ROUNDS` | 同一轮里模型连续调用工具的次数。到了还没给出文字就停 | `8` |

扫码登录（不把 token 打到终端）：

```bash
python -m xiaoluozi.channels
```

确认之后把 `WEIXIN_ENABLED=true` 写进 `.env`，再重启 `python -m xiaoluozi`。微信里的话会出现在网页对话里，网页里的话也会进入下一轮发给模型的上下文。

Hindsight 未配置或连不上时，回复照常返回，页面会轻轻注明这一轮没有存进记忆。已配置时，先按用户的话召回，放进交给代理的请求。laya 不走包装器。代理调用大模型时仍用 `hindsight_litellm.wrap_openai`。回路另外把这一轮收成一份对话文档，`document_id` 用这一轮的 `turn_id`，认知栏写的是 laya 明确的意图。`kb` 不召回，也不写入这份记忆。不安装 Hindsight 服务，地址用 `.env` 里已经部署的那份。变量示例见 `.env.example`。

## 测试

单元测试使用假的模型客户端和假的记忆端口，不访问 Venus 或 Hindsight。

```bash
pytest
```
