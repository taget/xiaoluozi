"""WeChat channel over the same iLink bot API OpenClaw's openclaw-weixin plugin uses.

Text in and text out share the workbench session. Media upload stays out of this process.
"""

import base64
import json
import os
import random
import threading
import time
import uuid
from pathlib import Path

import httpx

from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.weixin")

ILINK_APP_ID = "bot"
CHANNEL_VERSION = "2.1.8"
CLIENT_VERSION = (2 << 16) | (1 << 8) | 8
LOGIN_BASE_URL = "https://ilinkai.weixin.qq.com"
LONG_POLL_TIMEOUT = 35.0
SEND_TIMEOUT = 15.0
MESSAGE_TYPE_BOT = 2
ITEM_TEXT = 1
ITEM_VOICE = 3


def sync_path(root: Path, account_id: str) -> Path:
    return root / "data" / "weixin" / f"{account_id}.sync.json"


def _common_headers() -> dict[str, str]:
    return {
        "iLink-App-Id": ILINK_APP_ID,
        "iLink-App-ClientVersion": str(CLIENT_VERSION),
    }


def _post_headers(token: str) -> dict[str, str]:
    uin = base64.b64encode(str(random.randrange(2**32)).encode()).decode()
    return {
        "Content-Type": "application/json",
        "AuthorizationType": "ilink_bot_token",
        "Authorization": f"Bearer {token}",
        "X-WECHAT-UIN": uin,
        **_common_headers(),
    }


def message_text(message: dict) -> str:
    if message.get("message_type") == MESSAGE_TYPE_BOT:
        return ""
    parts = []
    for item in message.get("item_list") or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        if kind == ITEM_TEXT:
            text = (item.get("text_item") or {}).get("text")
        elif kind == ITEM_VOICE:
            text = (item.get("voice_item") or {}).get("text")
        else:
            text = ""
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n".join(parts)


class WeixinApi:
    def __init__(self, base_url: str, token: str, client: httpx.Client | None = None):
        self.base_url = base_url.strip().rstrip("/")
        self.token = token.strip()
        self._client = client or httpx.Client(timeout=LONG_POLL_TIMEOUT + 5)

    def get_updates(self, cursor: str) -> dict:
        body = {
            "get_updates_buf": cursor,
            "base_info": {"channel_version": CHANNEL_VERSION},
        }
        try:
            response = self._client.post(
                f"{self.base_url}/ilink/bot/getupdates",
                headers=_post_headers(self.token),
                json=body,
                timeout=LONG_POLL_TIMEOUT + 5,
            )
        except httpx.TimeoutException:
            logger.info("微信长轮询超时，继续下一轮。")
            return {"ret": 0, "msgs": [], "get_updates_buf": cursor}
        except httpx.HTTPError as exc:
            logger.info("微信长轮询失败 %s", type(exc).__name__)
            raise
        return _json_body(response, "微信长轮询")

    def send_text(self, to_user_id: str, text: str, context_token: str | None) -> None:
        message = {
            "from_user_id": "",
            "to_user_id": to_user_id,
            "client_id": uuid.uuid4().hex,
            "message_type": MESSAGE_TYPE_BOT,
            "message_state": 2,
            "item_list": [{"type": ITEM_TEXT, "text_item": {"text": text}}],
        }
        if context_token:
            message["context_token"] = context_token
        body = {"msg": message, "base_info": {"channel_version": CHANNEL_VERSION}}
        try:
            response = self._client.post(
                f"{self.base_url}/ilink/bot/sendmessage",
                headers=_post_headers(self.token),
                json=body,
                timeout=SEND_TIMEOUT,
            )
        except httpx.HTTPError as exc:
            logger.info("微信发送失败 %s", type(exc).__name__)
            raise
        if response.status_code >= 400:
            logger.info("微信发送失败 status=%s", response.status_code)
            raise RuntimeError("微信发送失败。")


class WeixinChannel:
    """Poll iLink and hand each text to the shared workbench entry."""

    def __init__(self, api: WeixinApi, handle, sync_file: Path):
        self.api = api
        self._handle = handle
        self.sync_file = sync_file
        self.cursor = _load_cursor(sync_file)

    def poll_once(self) -> int:
        payload = self.api.get_updates(self.cursor)
        ret = payload.get("ret", 0)
        errcode = payload.get("errcode", 0)
        if ret == -14 or errcode == -14:
            logger.info("微信登录已过期。重新扫码登录后再收消息。")
            return 0
        if ret not in (None, 0) or errcode not in (None, 0):
            logger.info("微信长轮询返回 ret=%s errcode=%s", ret, errcode)
            return 0
        cursor = payload.get("get_updates_buf")
        if isinstance(cursor, str) and cursor:
            self.cursor = cursor
            _save_cursor(self.sync_file, cursor)
        handled = 0
        for message in payload.get("msgs") or []:
            if not isinstance(message, dict):
                continue
            text = message_text(message)
            if not text:
                continue
            to_user = message.get("from_user_id") or ""
            context_token = message.get("context_token")
            if not isinstance(context_token, str):
                context_token = None
            logger.info("微信收到 %s", text)
            try:
                reply = self._handle(text, channel="weixin")
            except Exception as exc:
                detail = str(exc).strip() or "这一轮没有回复。"
                logger.info("微信回复失败 %s", detail)
                self._send(to_user, detail, context_token)
                continue
            self._send(to_user, reply.text, context_token)
            handled += 1
        return handled

    def run(self, stop: threading.Event) -> None:
        logger.info("微信通道开始接收")
        while not stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                logger.info("微信通道这一轮失败 %s", type(exc).__name__)
                stop.wait(2)
        logger.info("微信通道停止接收")

    def _send(self, to_user: str, text: str, context_token: str | None) -> None:
        if not to_user or not text.strip():
            return
        try:
            self.api.send_text(to_user, text, context_token)
        except Exception as exc:
            logger.info("微信发送失败 %s", type(exc).__name__)


def save_account(path: Path, *, token: str, base_url: str, user_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "token": token,
        "baseUrl": base_url,
        "userId": user_id,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def start_login(client: httpx.Client) -> dict:
    response = client.get(
        f"{LOGIN_BASE_URL}/ilink/bot/get_bot_qrcode",
        params={"bot_type": "3"},
        headers=_common_headers(),
        timeout=15,
    )
    body = _json_body(response, "微信登录")
    qrcode = body.get("qrcode")
    image = body.get("qrcode_img_content")
    if not isinstance(qrcode, str) or not qrcode or not isinstance(image, str) or not image:
        raise RuntimeError("微信没有返回二维码。")
    return {"qrcode": qrcode, "image": image}


def finish_login(status: dict, path: Path) -> str:
    if status.get("status") != "confirmed":
        return "还没有确认登录。"
    token = status.get("bot_token")
    account_id = status.get("ilink_bot_id")
    base_url = status.get("baseurl") or LOGIN_BASE_URL
    user_id = status.get("ilink_user_id") or ""
    if not isinstance(token, str) or not token.strip() or not isinstance(account_id, str) or not account_id.strip():
        raise RuntimeError("登录失败：服务器没有返回账号。")
    save_account(path, token=token.strip(), base_url=str(base_url).strip(), user_id=str(user_id).strip())
    return "微信已连接。账号写在 data/weixin/account.json。把 WEIXIN_ENABLED 设为 true，然后重启小落子。"


def run_login(path: Path, client: httpx.Client | None = None) -> str:
    owns_client = client is None
    client = client or httpx.Client(timeout=40)
    try:
        started = start_login(client)
        print(f"用微信打开这个链接扫码：\n{started['image']}", flush=True)
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                response = client.get(
                    f"{LOGIN_BASE_URL}/ilink/bot/get_qrcode_status",
                    params={"qrcode": started["qrcode"]},
                    headers=_common_headers(),
                    timeout=40,
                )
                status = _json_body(response, "微信登录")
            except (httpx.TimeoutException, httpx.HTTPError):
                continue
            state = status.get("status")
            if state == "confirmed":
                return finish_login(status, path)
            if state == "expired":
                started = start_login(client)
                print(f"二维码过期了，用新链接再扫一次：\n{started['image']}", flush=True)
        return "登录超时。再运行一次 python -m xiaoluozi.channels。"
    finally:
        if owns_client:
            client.close()


def _json_body(response: httpx.Response, label: str) -> dict:
    if response.status_code >= 400:
        logger.info("%s失败 status=%s", label, response.status_code)
        raise RuntimeError(f"{label}失败。")
    try:
        body = response.json()
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{label}没有返回 JSON。") from exc
    if not isinstance(body, dict):
        raise RuntimeError(f"{label}没有返回 JSON。")
    return body


def _load_cursor(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    cursor = data.get("get_updates_buf") if isinstance(data, dict) else ""
    return cursor if isinstance(cursor, str) else ""


def _save_cursor(path: Path, cursor: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"get_updates_buf": cursor}), encoding="utf-8")
