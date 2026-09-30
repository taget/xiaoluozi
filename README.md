# 小落子

一个 Python 进程上的个人助手工作台。你写一句话，进程里的回路先路由、再让兜底代理回复、然后抽出一条短认知，并把这一轮写入外部记忆。页面只显示回复。

用户的一句话进来后，先拉取上下文和已启用的代理，再让 laya 决定用哪个代理，并明确意图。然后把这句话、上下文和意图交给那个代理，由它请求一次大模型。没有合适的代理时用默认代理，意图照样传过去。`chat` 是日常对话，也是默认代理。`qa` 回答需要说明或解释的问题。代理实现在代码里，启用名单在 `.env`。它们不调用工具，也不自己写记忆。

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
| `ENABLED_AGENTS` | 启用的代理 id，逗号分隔。实现必须在代码里 | `chat,qa` |
| `DEFAULT_AGENT` | 没有合适代理时使用的代理 | `chat` |
| `WEIXIN_ENABLED` | 是否接收微信消息 | `false` |
| `WEIXIN_BOT_TOKEN` | 微信 iLink bot token。留空时，在通道已启用的前提下改读 `data/weixin/account.json` | 无 |
| `WEIXIN_BASE_URL` | iLink 接口地址。登录文件里有 `baseUrl` 且这里没写时，用登录文件里的地址 | `https://ilinkai.weixin.qq.com` |
| `WEIXIN_ACCOUNT_ID` | 同步游标文件名 | `default` |

扫码登录（不把 token 打到终端）：

```bash
python -m xiaoluozi.channels
```

确认之后把 `WEIXIN_ENABLED=true` 写进 `.env`，再重启 `python -m xiaoluozi`。微信里的话会出现在网页对话里，网页里的话也会进入下一轮发给模型的上下文。

Hindsight 未配置或连不上时，回复照常返回，页面会轻轻注明这一轮没有存进记忆。已配置时，先按用户的话召回，放进 laya 的 `state`，也放进交给代理的请求。laya 不走包装器。代理调用大模型时仍用 `hindsight_litellm.wrap_openai`。回路另外把这一轮收成一份对话文档，`document_id` 用这一轮的 `turn_id`，认知栏写的是 laya 明确的意图。不安装 Hindsight 服务，地址用 `.env` 里已经部署的那份。变量示例见 `.env.example`。

## 测试

单元测试使用假的模型客户端和假的记忆端口，不访问 Venus 或 Hindsight。

```bash
pytest
```
