"""Knot knowledge MCP. One HTTP session searches the configured knowledge base."""

import json
import re

import httpx

from xiaoluozi.errors import ReplyError
from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.knot_mcp")

MCP_URL = "http://mcp.knot.woa.com/open/mcp"
KNOWLEDGE_UUID = "c348be776d4545e4903acc295c19c72c"
SEARCH_DOMAIN = "eliqiao-67bcf1a4b9e8ade8d5420db47f0fd269"
_PROTOCOL = "2025-03-26"
_FAILED = "CVM 底层知识库调用失败。"
_MATERIAL_LIMIT = 12000


class KnotMcp:
    """Call knowledgebase_search on the Knot MCP server. The token stays in the header."""

    def __init__(self, token: str, *, url: str = MCP_URL, transport=None):
        self._token = token.strip()
        self._url = url
        self._transport = transport

    def search(self, query: str, keyword: str) -> str:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-knot-knowledge-uuids": KNOWLEDGE_UUID,
            "X-knot-api-token": self._token,
        }
        with httpx.Client(transport=self._transport, timeout=60) as client:
            opened = self._post(
                client,
                headers,
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": _PROTOCOL,
                        "capabilities": {},
                        "clientInfo": {"name": "xiaoluozi", "version": "0.1.0"},
                    },
                },
            )
            session = opened.headers.get("mcp-session-id", "").strip()
            if not session:
                logger.info("知识库检索失败 没有会话")
                raise ReplyError(_FAILED)
            headers = {**headers, "Mcp-Session-Id": session}
            self._post(client, headers, {"jsonrpc": "2.0", "method": "notifications/initialized"})
            found = self._post(
                client,
                headers,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "knowledgebase_search",
                        "arguments": {
                            "query": query,
                            "keyword": keyword,
                            "knowledge_uuid": KNOWLEDGE_UUID,
                            "data_type": "document",
                            "search_domain": SEARCH_DOMAIN,
                        },
                    },
                },
            )
        payload = _payload(found)
        if payload.get("error"):
            logger.info("知识库检索失败 rpc")
            raise ReplyError(_FAILED)
        result = payload.get("result")
        if not isinstance(result, dict) or result.get("isError"):
            logger.info("知识库检索失败 结果不可用")
            raise ReplyError(_FAILED)
        return format_knowledge(_content_text(result))

    def _post(self, client: httpx.Client, headers: dict, body: dict) -> httpx.Response:
        try:
            response = client.post(self._url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            logger.info("知识库检索失败 %s", exc.__class__.__name__)
            raise ReplyError(_FAILED) from exc
        if response.status_code >= 400:
            logger.info("知识库检索失败 %s", response.status_code)
            raise ReplyError(_FAILED)
        return response


def search_keywords(message: str) -> str:
    """Keywords for knowledgebase_search. Punctuation becomes separators."""
    text = re.sub(r"[\s,，。！？、；;：:]+", ";", (message or "").strip())
    text = re.sub(r";+", ";", text).strip(";")
    return text


def format_knowledge(text: str) -> str:
    """Turn the tool's chunk JSON into titled excerpts. Empty when nothing matched."""
    raw = (text or "").strip()
    if not raw or raw == "[]":
        return ""
    chunks = _chunks(raw)
    if chunks is None:
        return _clip(raw)
    parts = []
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        title = str(chunk.get("chunk_title") or "未命名").strip() or "未命名"
        body = str(chunk.get("chunk_content") or "").strip()
        if not body:
            continue
        block = f"【{title}】"
        href = _href(chunk)
        if href:
            block += f"\n链接：{href}"
        parts.append(f"{block}\n{body}")
    return _clip("\n\n".join(parts).strip())


def citation_tail(answer: str, material: str) -> str:
    """Lines to append so each distinct source becomes a link. Empty when none are new."""
    seen: set[str] = set()
    lines = []
    body = answer or ""
    for title, url in _links(material):
        if url in seen or url in body:
            continue
        seen.add(url)
        lines.append(f"{len(lines) + 1}. [{_link_label(title)}]({url})")
    if not lines:
        return ""
    prefix = "\n\n" if body.strip() else ""
    return prefix + "引用：\n" + "\n".join(lines)


def _href(chunk: dict) -> str:
    raw = chunk.get("href")
    if isinstance(raw, str):
        url = raw.strip()
        if re.fullmatch(r"https?://[^\s)]+", url):
            return url
    doc_id = str(chunk.get("doc_id") or "").strip()
    if re.fullmatch(r"\d{3,}", doc_id):
        return f"https://iwiki.woa.com/p/{doc_id}"
    return ""


def _links(material: str):
    lines = (material or "").splitlines()
    for index, line in enumerate(lines):
        match = re.fullmatch(r"链接：(https?://[^\s)]+)", line.strip())
        if not match:
            continue
        title = "未命名"
        if index:
            raw = lines[index - 1].strip()
            if raw.startswith("【") and raw.endswith("】") and len(raw) > 2:
                title = raw[1:-1].strip() or "未命名"
        yield title, match.group(1)


def _link_label(title: str) -> str:
    return title.replace("[", "［").replace("]", "］") or "未命名"


def _chunks(text: str):
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, list):
        return parsed
    return None


def _clip(text: str) -> str:
    if len(text) <= _MATERIAL_LIMIT:
        return text
    return text[:_MATERIAL_LIMIT].rstrip() + "\n\n后面的材料被截断了。"


def _content_text(result: dict) -> str:
    parts = []
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
    return "\n".join(parts)


def _payload(response: httpx.Response) -> dict:
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[len("data:") :].strip()
            if not data or data == "[DONE]":
                continue
            try:
                parsed = json.loads(data)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        logger.info("知识库检索失败 流里没有结果")
        raise ReplyError(_FAILED)
    try:
        parsed = response.json()
    except json.JSONDecodeError as exc:
        logger.info("知识库检索失败 响应不是 JSON")
        raise ReplyError(_FAILED) from exc
    if not isinstance(parsed, dict):
        raise ReplyError(_FAILED)
    return parsed
