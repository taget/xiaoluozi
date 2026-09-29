# 小落子

一个 Python 进程上的个人助手工作台。你写一句话，进程里的回路先路由、再让兜底代理回复、然后抽出一条短认知，并把这一轮写入外部记忆。页面只显示回复。

这一版只有一个代理 `chat`：日常对话，也是没有专职代理时的兜底。它做一次对话补全，不调用工具，也不自己写记忆。微信、QQ 以后可以调用同一个入口，这一版不实现那些适配器。

```python
from xiaoluozi import handle

reply = handle("今天要不要出门")
reply.text   # 给对方看的那一句
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

## 环境变量

密钥只放在环境里，不要写进仓库。

| 变量 | 作用 | 默认 |
| --- | --- | --- |
| `TYPESAFE_API_KEY` | OpenAI 兼容接口的密钥 | 无。缺了页面会说明模型还没配好，不会编一条假回复 |
| `TYPESAFE_BASE_URL` | 接口根地址。请求发到 `{BASE_URL}/chat/completions` | `http://v2.open.venus.oa.com/llmproxy` |
| `TYPESAFE_DEFAULT_MODEL` | 路由、回复、认知三次调用用的模型 | `jev-1.13.0` |
| `HINDSIGHT_BASE_URL` | [Hindsight](https://github.com/vectorize-io/hindsight) 服务地址 | 无 |
| `HINDSIGHT_BANK_ID` | 唯一的记忆库 | 无 |

Hindsight 未配置或连不上时，回复照常返回，页面会轻轻注明这一轮没有存进记忆。写入使用当前的 retain 接口：`POST {HINDSIGHT_BASE_URL}/v1/default/banks/{HINDSIGHT_BANK_ID}/memories`。每一轮四条带标签的内容共用一个 `turn_id`：用户的话、路由决定、助手回复、认知（提取失败时是一条明确的失败说明）。这一版只写不读。

## 测试

单元测试使用假的模型客户端和假的记忆端口，不访问 Venus 或 Hindsight。

```bash
pytest
```
