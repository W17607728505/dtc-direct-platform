# -*- coding: utf-8 -*-
"""
社媒通道适配器 + OAuth2 授权框架
- 每个平台一个适配器，统一 authorize / exchange / refresh / deliver / revoke 接口
- 未配置凭证时自动进入沙箱模式：流程可完整演示，但明确标注为模拟
- 数据边界：只走官方 API 授权字段；不抓取、不跨平台合并身份、不外传用户数据
"""
import base64
import json
import os
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta


def iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_dt(s):
    return datetime.fromisoformat(s)


class AdapterError(Exception):
    pass


_SALT = b"dtc-mvp-demo"


def _obfuscate(s):
    """演示用令牌混淆（生产环境须改用 KMS / 密钥管理服务）"""
    data = bytes(b ^ _SALT[i % len(_SALT)] for i, b in enumerate(s.encode("utf-8")))
    return base64.b64encode(data).decode("ascii")


class BaseAdapter:
    key = ""
    label = ""
    real_capable = False
    scopes = []
    rate = {"minute": 10, "day": 100}
    constraint = ""
    auth_base = ""

    @property
    def configured(self):
        return False

    @property
    def sandbox(self):
        return not self.configured

    def _client_id(self):
        return "sandbox_client"

    def authorize_url(self, state, redirect_uri):
        q = urllib.parse.urlencode({
            "client_id": self._client_id(), "redirect_uri": redirect_uri,
            "response_type": "code", "scope": " ".join(self.scopes), "state": state,
        })
        return self.auth_base + ("&" if "?" in self.auth_base else "?") + q

    def exchange(self, code, redirect_uri):
        if self.sandbox:
            return {"access_token": "sbx_at_" + secrets.token_hex(8),
                    "refresh_token": "sbx_rt_" + secrets.token_hex(8),
                    "expires_in": 3600, "scope": " ".join(self.scopes),
                    "open_id": "sbx_" + secrets.token_hex(4)}
        return self._exchange_real(code, redirect_uri)

    def _exchange_real(self, code, redirect_uri):
        raise AdapterError("真实令牌交换未配置")

    def refresh(self, conn):
        if self.sandbox:
            conn["access_token"] = "sbx_at_" + secrets.token_hex(8)
            conn["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=3600)).isoformat(timespec="seconds")
            return conn
        return self._refresh_real(conn)

    def _refresh_real(self, conn):
        raise AdapterError("真实令牌刷新未配置")

    def deliver(self, conn, payload):
        if self.sandbox:
            return {"ok": True, "sandbox": True, "message_id": "sbx_m_" + secrets.token_hex(6),
                    "channel": self.key, "delivered_at": iso(), "text": payload.get("text", "")[:80]}
        return self._deliver_real(conn, payload)

    def _deliver_real(self, conn, payload):
        raise AdapterError("真实投递未配置")

    def revoke(self, conn):
        return {"ok": True, "sandbox": self.sandbox, "revoked_at": iso()}

    def describe(self):
        return {
            "key": self.key, "label": self.label, "real_capable": self.real_capable,
            "sandbox": self.sandbox, "scopes": self.scopes, "rate_limit": self.rate,
            "constraint": self.constraint,
            "data_boundary": "仅官方 API 授权字段；不抓取、不跨平台合并身份、不外传用户数据",
            "auth_url_template": self.auth_base,
        }


class TelegramAdapter(BaseAdapter):
    key = "telegram"; label = "Telegram Bot"; real_capable = True
    scopes = ["send_message"]; rate = {"minute": 30, "day": 1000}
    constraint = "用户须先主动与 Bot 建立会话；禁止未经请求的群发；消息内容需符合平台政策"
    auth_base = "https://oauth.telegram.org/auth"

    @property
    def configured(self):
        return bool(os.environ.get("DTC_TELEGRAM_TOKEN"))

    def _client_id(self):
        return os.environ.get("DTC_TELEGRAM_BOT_ID", "sandbox_bot")

    def _deliver_real(self, conn, payload):
        token = os.environ["DTC_TELEGRAM_TOKEN"]
        chat_id = conn.get("open_id")
        url = "https://api.telegram.org/bot%s/sendMessage" % token
        data = json.dumps({"chat_id": chat_id, "text": payload.get("text", "")}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return {"ok": True, "sandbox": False, "response": json.loads(r.read().decode("utf-8"))}


class WechatAdapter(BaseAdapter):
    key = "wechat"; label = "微信订阅消息"; real_capable = True
    scopes = ["subscribe_message"]; rate = {"minute": 60, "day": 500}
    constraint = "用户须先授权订阅；模板 ID 与字段受限；一次性订阅仅可发一条；禁止诱导授权"
    auth_base = "https://open.weixin.qq.com/connect/oauth2/authorize"

    @property
    def configured(self):
        return bool(os.environ.get("DTC_WECHAT_APPID"))

    def _client_id(self):
        return os.environ.get("DTC_WECHAT_APPID", "sandbox_appid")

    def _deliver_real(self, conn, payload):
        appid = os.environ["DTC_WECHAT_APPID"]
        secret = os.environ.get("DTC_WECHAT_SECRET", "")
        url = ("https://api.weixin.qq.com/cgi-bin/message/subscribe/send"
               "?access_token=" + urllib.parse.quote(conn.get("access_token", "")))
        data = json.dumps({"touser": conn.get("open_id"), "template_id": payload.get("template_id", ""),
                           "data": payload.get("data", {})}, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return {"ok": True, "sandbox": False, "response": json.loads(r.read().decode("utf-8"))}


class MetaAdapter(BaseAdapter):
    key = "messenger"; label = "Meta Messenger"; real_capable = True
    scopes = ["pages_messaging"]; rate = {"minute": 20, "day": 500}
    constraint = "24 小时互动窗口外需使用付费标签；须由 Page 管理员授权；不得用于垃圾营销"
    auth_base = "https://www.facebook.com/v19.0/dialog/oauth"

    @property
    def configured(self):
        return bool(os.environ.get("DTC_META_APPID"))

    def _client_id(self):
        return os.environ.get("DTC_META_APPID", "sandbox_meta_app")

    def _deliver_real(self, conn, payload):
        url = "https://graph.facebook.com/v19.0/me/messages?access_token=" + urllib.parse.quote(conn.get("access_token", ""))
        data = json.dumps({"recipient": {"id": conn.get("open_id")},
                           "message": {"text": payload.get("text", "")}}).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as r:
            return {"ok": True, "sandbox": False, "response": json.loads(r.read().decode("utf-8"))}


class XAdapter(BaseAdapter):
    key = "x"; label = "X (Twitter) DM"; real_capable = True
    scopes = ["dm.write", "tweet.read"]; rate = {"minute": 10, "day": 200}
    constraint = "用户须先关注账号或主动发起 DM；DM 频率受限；禁止自动化骚扰"
    auth_base = "https://x.com/i/oauth2/authorize"

    @property
    def configured(self):
        return bool(os.environ.get("DTC_X_CLIENT_ID"))

    def _client_id(self):
        return os.environ.get("DTC_X_CLIENT_ID", "sandbox_x_app")


ADAPTERS = {a.key: a for a in [TelegramAdapter(), WechatAdapter(), MetaAdapter(), XAdapter()]}


def public_conn(c):
    """对外展示脱敏后的连接信息，令牌不出后端"""
    out = {k: v for k, v in c.items() if k not in ("access_token", "refresh_token")}
    out["token_masked"] = "****" + c.get("access_token", "")[-4:]
    return out


class OAuthManager:
    def __init__(self, adapters=None):
        self.adapters = adapters or ADAPTERS

    def describe_all(self):
        return [a.describe() for a in self.adapters.values()]

    def start(self, store, key, did, redirect_uri):
        a = self.adapters.get(key)
        if not a:
            raise AdapterError("未知通道适配器: " + str(key))
        state = secrets.token_urlsafe(18)
        store.setdefault("oauth_states", {})[state] = {"did": did, "key": key, "ts": iso()}
        return {"state": state, "authorize_url": a.authorize_url(state, redirect_uri),
                "adapter": a.describe()}

    def callback(self, store, key, code, state):
        rec = store.get("oauth_states", {}).pop(state, None)
        if not rec or rec["key"] != key:
            raise AdapterError("无效的 state（已过期或疑似 CSRF）")
        a = self.adapters[key]
        tok = a.exchange(code, "")
        conn = {
            "adapter": key, "did": rec["did"],
            "access_token": _obfuscate(tok["access_token"]),
            "refresh_token": _obfuscate(tok.get("refresh_token", "")),
            "expires_at": (datetime.now(timezone.utc) + timedelta(seconds=tok.get("expires_in", 3600))).isoformat(timespec="seconds"),
            "open_id": tok.get("open_id", ""), "scope": tok.get("scope", ""),
            "connected_at": iso(), "sandbox": a.sandbox,
        }
        conns = [c for c in store.get("oauth_connections", [])
                 if not (c["adapter"] == key and c["did"] == rec["did"])]
        conns.append(conn)
        store["oauth_connections"] = conns
        return public_conn(conn)

    def connection(self, store, did, key):
        return next((c for c in store.get("oauth_connections", [])
                     if c["did"] == did and c["adapter"] == key), None)

    def connections(self, store, did=None):
        return [public_conn(c) for c in store.get("oauth_connections", [])
                if did is None or c["did"] == did]

    def revoke(self, store, did, key):
        conn = self.connection(store, did, key)
        if not conn:
            raise AdapterError("未连接该通道")
        result = self.adapters[key].revoke(conn)
        store["oauth_connections"] = [c for c in store["oauth_connections"] if c is not conn]
        return result

    def rate_usage(self, store, did, key):
        a = self.adapters[key]
        nowdt = datetime.now(timezone.utc)
        calls = [c for c in store.get("oauth_calls", []) if c["did"] == did and c["adapter"] == key]
        def within(td):
            return sum(1 for c in calls if parse_dt(c["ts"]) >= nowdt - td)
        minute, day = within(timedelta(minutes=1)), within(timedelta(days=1))
        return {"minute": minute, "day": day, "limit": a.rate,
                "ok": minute < a.rate["minute"] and day < a.rate["day"]}

    def deliver(self, store, did, key, payload):
        conn = self.connection(store, did, key)
        if not conn:
            raise AdapterError("用户未授权连接该通道")
        a = self.adapters[key]
        usage = self.rate_usage(store, did, key)
        if not usage["ok"]:
            raise AdapterError("触发平台速率限制: " + json.dumps(usage, ensure_ascii=False))
        if parse_dt(conn["expires_at"]) <= datetime.now(timezone.utc):
            a.refresh(conn)
            conn["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=3600)).isoformat(timespec="seconds")
        result = a.deliver(conn, payload)
        store.setdefault("oauth_calls", []).append({"did": did, "adapter": key, "ts": iso()})
        result["rate_usage"] = self.rate_usage(store, did, key)
        return result


oauth = OAuthManager()
