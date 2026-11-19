# -*- coding: utf-8 -*-
"""
DTC 直达用户平台 —— 最小可行产品 (MVP) 后端
零第三方依赖：仅使用 Python 标准库。

核心闭环：
  用户授权(同意账本) -> 商品发布 -> 兴趣匹配 -> 合规多通道分发
  -> 曝光/点击/成交追踪 -> 变现分账
"""
import json
import os
import re
import secrets
import string
import time
import uuid
import threading
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, unquote

import config
import adapters
import federation
import federated_rec
import growth

BASE_DIR = config.BASE_DIR
DATA_DIR = config.DATA_DIR
PUBLIC_DIR = config.PUBLIC_DIR
STORE_PATH = config.STORE_PATH
PORT = config.PORT
BASE_URL = config.BASE_URL

_lock = threading.Lock()

# 简易内存限流：{ip: [timestamp,...]}
_rate_hits = defaultdict(list)
_rate_lock = threading.Lock()


def rate_allowed(ip):
    if not config.ENABLE_RATE_LIMIT:
        return True
    now_ts = time.time()
    with _rate_lock:
        hits = _rate_hits[ip]
        cutoff = now_ts - 60
        hits[:] = [t for t in hits if t > cutoff]
        if len(hits) >= config.RATE_LIMIT_PER_MIN:
            return False
        hits.append(now_ts)
        return True

# 通道定义：inbox 为真实可达的主权通道；email/webpush 为模拟适配器（接入 SMTP/VAPID 即可真实投递）
CHANNELS = {
    "inbox":   {"label": "站内触达", "desc": "平台自有站内消息，零依赖、真实可达", "real": True},
    "email":   {"label": "邮件", "desc": "模拟投递：记录投递事件，接入 SMTP 后可真实发送", "real": False},
    "webpush": {"label": "Web Push", "desc": "模拟投递：接入 VAPID 后可真实推送", "real": False},
}


# ---------- 基础工具 ----------
def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def newid(prefix):
    return "%s_%s" % (prefix, uuid.uuid4().hex[:10])


def empty_store():
    return {
        "users": [], "products": [], "campaigns": [],
        "events": [], "orders": [], "meta": {"seeded": False},
        "oauth_states": {}, "oauth_connections": [], "oauth_calls": [],
        "ap_users": [], "ap_actors": {}, "ap_activities": [], "ap_inbox": {}, "ap_follows": [],
        "fl_model": {"version": 1, "rounds": 0, "epsilon": 1.0, "tag_weights": {}},
        "fl_updates": [],
        "shares": [], "templates": [], "invites": [], "visits": [],
    }


def load_store():
    if not os.path.exists(STORE_PATH):
        return empty_store()
    with open(STORE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_store(store):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = STORE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STORE_PATH)


def days_ago(n):
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat(timespec="seconds")


# ---------- 演示种子数据 ----------
def seed(store, base_url=None):
    store["users"] = [
        {"did": "did:dtc:u1", "name": "林晓", "interests": ["AI", "效率工具", "阅读"],
         "consents": {"inbox": {"enabled": True, "max_per_week": 5},
                      "email": {"enabled": True, "max_per_week": 3},
                      "webpush": {"enabled": False, "max_per_week": 3}}, "created_at": days_ago(30)},
        {"did": "did:dtc:u2", "name": "陈默", "interests": ["健身", "健康", "户外"],
         "consents": {"inbox": {"enabled": True, "max_per_week": 4},
                      "email": {"enabled": False, "max_per_week": 3},
                      "webpush": {"enabled": True, "max_per_week": 3}}, "created_at": days_ago(21)},
        {"did": "did:dtc:u3", "name": "苏苏", "interests": ["AI", "设计", "效率工具"],
         "consents": {"inbox": {"enabled": True, "max_per_week": 5},
                      "email": {"enabled": True, "max_per_week": 3},
                      "webpush": {"enabled": True, "max_per_week": 3}}, "created_at": days_ago(14)},
        {"did": "did:dtc:u4", "name": "王凯", "interests": ["美食", "旅行", "摄影"],
         "consents": {"inbox": {"enabled": False, "max_per_week": 3},
                      "email": {"enabled": True, "max_per_week": 2},
                      "webpush": {"enabled": False, "max_per_week": 3}}, "created_at": days_ago(9)},
    ]
    store["products"] = [
        {"id": "p1", "title": "AI 写作助手 Pro", "desc": "基于大模型的长文写作与改写工具", "price": 99.0,
         "tags": ["AI", "效率工具", "写作"], "owner": "创作者A", "created_at": days_ago(12)},
        {"id": "p2", "title": "极简阅读器", "desc": "沉浸式阅读与稍后读管理", "price": 38.0,
         "tags": ["阅读", "效率工具", "设计"], "owner": "创作者B", "created_at": days_ago(10)},
        {"id": "p3", "title": "居家健身计划", "desc": "12 周科学训练与饮食方案", "price": 129.0,
         "tags": ["健身", "健康"], "owner": "创作者C", "created_at": days_ago(8)},
        {"id": "p4", "title": "设计素材套装", "desc": "UI 图标与模板合集", "price": 59.0,
         "tags": ["设计", "效率工具"], "owner": "创作者A", "created_at": days_ago(6)},
        {"id": "p5", "title": "城市摄影指南", "desc": "24 座城市的出片机位地图", "price": 45.0,
         "tags": ["摄影", "旅行"], "owner": "创作者D", "created_at": days_ago(4)},
    ]
    store["campaigns"] = [
        {"id": "c1", "name": "AI 写作助手首发", "product_id": "p1", "channel": "inbox", "created_at": days_ago(6), "sent": 2},
        {"id": "c2", "name": "阅读器新品触达", "product_id": "p2", "channel": "email", "created_at": days_ago(4), "sent": 2},
    ]
    store["events"] = []
    # 曝光
    for did, pid, ch, camp in [("did:dtc:u1", "p1", "inbox", "c1"), ("did:dtc:u3", "p1", "inbox", "c1"),
                               ("did:dtc:u1", "p2", "email", "c2"), ("did:dtc:u3", "p2", "email", "c2")]:
        store["events"].append({"id": newid("e"), "type": "impression", "did": did, "product_id": pid,
                                "campaign_id": camp, "channel": ch, "ts": days_ago(3)})
    # 点击
    for did, pid, camp in [("did:dtc:u1", "p1", "c1"), ("did:dtc:u3", "p2", "c2")]:
        store["events"].append({"id": newid("e"), "type": "click", "did": did, "product_id": pid,
                                "campaign_id": camp, "channel": "inbox" if camp == "c1" else "email", "ts": days_ago(2)})
    # 成交
    store["events"].append({"id": newid("e"), "type": "purchase", "did": "did:dtc:u1", "product_id": "p1",
                            "campaign_id": "c1", "channel": "inbox", "ts": days_ago(1)})
    store["orders"] = [
        {"id": "o1", "did": "did:dtc:u1", "product_id": "p1", "amount": 99.0,
         "campaign_id": "c1", "channel": "inbox", "ts": days_ago(1)},
    ]
    federation.seed_federation(store, base_url or BASE_URL)
    store["meta"]["seeded"] = True


# ---------- 业务逻辑 ----------
def find_user(store, did):
    return next((u for u in store["users"] if u["did"] == did), None)


def find_product(store, pid):
    return next((p for p in store["products"] if p["id"] == pid), None)


def score_product(user, product, store):
    matched = sorted(set(user.get("interests", [])) & set(product.get("tags", [])))
    pop = sum(1 for e in store["events"]
              if e.get("product_id") == product["id"] and e.get("type") in ("click", "purchase"))
    score = len(matched) * 3 + min(pop, 10) * 0.2
    return round(score, 2), matched


def recent_impressions(store, did, channel):
    cutoff = datetime.now(timezone.utc) - timedelta(days=7)
    n = 0
    for e in store["events"]:
        if e.get("did") == did and e.get("type") == "impression" and e.get("channel") == channel:
            try:
                if datetime.fromisoformat(e["ts"]) >= cutoff:
                    n += 1
            except Exception:
                pass
    return n


def has_consent(store, user, channel):
    c = user.get("consents", {}).get(channel, {})
    if not c.get("enabled"):
        return False, "no_consent"
    if recent_impressions(store, user["did"], channel) >= int(c.get("max_per_week", 3)):
        return False, "freq_cap"
    return True, "ok"


def add_event(store, etype, did, product_id=None, campaign_id=None, channel=None, meta=None):
    ev = {"id": newid("e"), "type": etype, "did": did, "product_id": product_id,
          "campaign_id": campaign_id, "channel": channel, "ts": now()}
    if meta:
        ev["meta"] = meta
    store["events"].append(ev)
    return ev


def get_stats(store):
    events = store["events"]
    counts = {t: sum(1 for e in events if e.get("type") == t) for t in ("impression", "click", "purchase")}
    gmv = round(sum(o["amount"] for o in store["orders"]), 2)
    imp = counts["impression"]
    return {
        "users": len(store["users"]),
        "products": len(store["products"]),
        "campaigns": len(store["campaigns"]),
        "funnel": counts,
        "gmv": gmv,
        "platform_fee": round(gmv * 0.10, 2),
        "creator_payout": round(gmv * 0.90, 2),
        "click_rate": round(counts["click"] / imp * 100, 1) if imp else 0,
        "conversion_rate": round(counts["purchase"] / imp * 100, 1) if imp else 0,
        "by_channel": {
            ch: sum(1 for e in events if e.get("type") == "impression" and e.get("channel") == ch)
            for ch in CHANNELS
        },
        "recent_events": list(reversed(events))[:12],
    }


# ---------- HTTP 处理 ----------
class Handler(BaseHTTPRequestHandler):
    server_version = "DTC-MVP/0.1"

    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.command, self.path))

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _parse(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        qs = parse_qs(parsed.query)
        body = {}
        if self.command in ("POST", "PUT", "PATCH"):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
            if raw:
                try:
                    body = json.loads(raw.decode("utf-8"))
                except Exception:
                    body = {}
        return path, qs, body

    def _static(self, path):
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(PUBLIC_DIR, rel))
        if not full.startswith(PUBLIC_DIR) or not os.path.isfile(full):
            self.send_error(404, "Not Found")
            return
        ext = os.path.splitext(full)[1].lower()
        mime = {".html": "text/html", ".js": "application/javascript", ".css": "text/css",
                ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png"}.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime + ("; charset=utf-8" if ext in (".html", ".js", ".css", ".json") else ""))
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _api(self, method, path, qs, body):
        store = load_store()

        # 元信息
        if method == "GET" and path == "/api/meta":
            return self._send_json({"channels": CHANNELS, "seeded": store["meta"].get("seeded", False)})

        if method == "POST" and path == "/api/reset":
            with _lock:
                fresh = empty_store()
                seed(fresh, BASE_URL)
                save_store(fresh)
            return self._send_json({"ok": True, "message": "已重置为演示数据"})
        # 数据快照：导出 / 恢复（应对无持久卷平台的重启数据丢失）
        if method == "GET" and path == "/api/snapshot":
            return self._send_json({"ok": True, "exported_at": now(), "data": store})
        if method == "POST" and path == "/api/snapshot":
            incoming = body.get("data")
            if not isinstance(incoming, dict):
                return self._send_json({"error": "无效快照数据"}, 400)
            with _lock:
                save_store(incoming)
            return self._send_json({"ok": True, "message": "快照已恢复"})

        # 用户
        if method == "GET" and path == "/api/users":
            return self._send_json(store["users"])
        if method == "POST" and path == "/api/users":
            with _lock:
                did = "did:dtc:" + uuid.uuid4().hex[:10]
                user = {"did": did, "name": (body.get("name") or "新用户").strip(),
                        "interests": body.get("interests") or [],
                        "consents": {ch: {"enabled": (ch == "inbox"), "max_per_week": 3} for ch in CHANNELS},
                        "created_at": now()}
                store["users"].append(user)
                save_store(store)
            return self._send_json(user, 201)
        m = re.match(r"^/api/users/([^/]+)/interests$", path)
        if method == "PUT" and m:
            did = m.group(1)
            with _lock:
                user = find_user(store, did)
                if not user:
                    return self._send_json({"error": "用户不存在"}, 404)
                user["interests"] = body.get("interests") or []
                save_store(store)
            return self._send_json(user)
        m = re.match(r"^/api/users/([^/]+)/consents$", path)
        if method == "PUT" and m:
            did = m.group(1)
            ch = body.get("channel")
            if ch not in CHANNELS:
                return self._send_json({"error": "未知通道"}, 400)
            with _lock:
                user = find_user(store, did)
                if not user:
                    return self._send_json({"error": "用户不存在"}, 404)
                user.setdefault("consents", {})[ch] = {
                    "enabled": bool(body.get("enabled")),
                    "max_per_week": int(body.get("max_per_week", 3)),
                }
                save_store(store)
            return self._send_json(user)

        # 商品
        if method == "GET" and path == "/api/products":
            return self._send_json(store["products"])
        if method == "POST" and path == "/api/products":
            if not (body.get("title") or "").strip():
                return self._send_json({"error": "商品标题必填"}, 400)
            with _lock:
                product = {"id": newid("p"), "title": body["title"].strip(),
                           "desc": body.get("desc", ""), "price": float(body.get("price", 0)),
                           "tags": body.get("tags") or [], "owner": body.get("owner") or "创作者",
                           "created_at": now()}
                store["products"].append(product)
                save_store(store)
            return self._send_json(product, 201)

        # 推荐
        if method == "GET" and path == "/api/recommendations":
            did = (qs.get("did") or [None])[0]
            user = find_user(store, did) if did else None
            if not user:
                return self._send_json({"error": "请指定有效用户 did"}, 400)
            result = []
            for p in store["products"]:
                sc, matched = score_product(user, p, store)
                if sc > 0:
                    result.append({**p, "score": sc, "matched": matched})
            result.sort(key=lambda x: (-x["score"], -x["price"]))
            return self._send_json(result)

        # 分发活动
        if method == "GET" and path == "/api/campaigns":
            return self._send_json(list(reversed(store["campaigns"])))
        if method == "POST" and path == "/api/campaigns":
            product = find_product(store, body.get("product_id"))
            ch = body.get("channel")
            if not product:
                return self._send_json({"error": "商品不存在"}, 400)
            if ch not in CHANNELS:
                return self._send_json({"error": "未知通道"}, 400)
            with _lock:
                camp = {"id": newid("c"), "name": body.get("name") or (product["title"] + " · 触达"),
                        "product_id": product["id"], "channel": ch, "created_at": now(), "sent": 0}
                sent = consent_skip = match_skip = freq_skip = 0
                for u in store["users"]:
                    sc, matched = score_product(u, product, store)
                    if not matched:
                        match_skip += 1
                        continue
                    ok, reason = has_consent(store, u, ch)
                    if not ok:
                        if reason == "no_consent":
                            consent_skip += 1
                        else:
                            freq_skip += 1
                        continue
                    add_event(store, "impression", u["did"], product["id"], camp["id"], ch,
                              {"matched": matched, "adapter_real": CHANNELS[ch]["real"]})
                    sent += 1
                camp["sent"] = sent
                store["campaigns"].append(camp)
                save_store(store)
            return self._send_json({"campaign": camp, "sent": sent,
                                    "skipped": {"no_consent": consent_skip, "no_match": match_skip,
                                                "freq_cap": freq_skip},
                                    "channel": CHANNELS[ch]}, 201)

        # 追踪：点击 / 成交
        if method == "POST" and path == "/api/click":
            with _lock:
                ev = add_event(store, "click", body.get("did"), body.get("product_id"),
                               body.get("campaign_id"), body.get("channel"))
                save_store(store)
            return self._send_json(ev, 201)
        if method == "POST" and path == "/api/purchase":
            product = find_product(store, body.get("product_id"))
            if not product:
                return self._send_json({"error": "商品不存在"}, 400)
            with _lock:
                add_event(store, "purchase", body.get("did"), product["id"],
                          body.get("campaign_id"), body.get("channel"))
                order = {"id": newid("o"), "did": body.get("did"), "product_id": product["id"],
                         "amount": product["price"], "campaign_id": body.get("campaign_id"),
                         "channel": body.get("channel"), "ts": now()}
                store["orders"].append(order)
                save_store(store)
            return self._send_json(order, 201)

        # ===== 社媒适配器与 OAuth2 =====
        if method == "GET" and path == "/api/adapters":
            return self._send_json(adapters.oauth.describe_all())
        if method == "POST" and path == "/api/oauth/start":
            key, did = body.get("key"), body.get("did")
            if key not in adapters.oauth.adapters:
                return self._send_json({"error": "未知通道适配器"}, 400)
            redirect = body.get("redirect_uri") or (BASE_URL + "/?oauth=callback")
            r = adapters.oauth.start(store, key, did, redirect)
            save_store(store)
            return self._send_json(r)
        if method == "POST" and path == "/api/oauth/callback":
            with _lock:
                try:
                    conn = adapters.oauth.callback(store, body.get("key"),
                                                   body.get("code", ""), body.get("state", ""))
                    save_store(store)
                except adapters.AdapterError as e:
                    return self._send_json({"error": str(e)}, 400)
            return self._send_json(conn)
        if method == "GET" and path == "/api/oauth/connections":
            did = (qs.get("did") or [None])[0]
            return self._send_json(adapters.oauth.connections(store, did))
        if method == "POST" and path == "/api/oauth/revoke":
            with _lock:
                try:
                    r = adapters.oauth.revoke(store, body.get("did"), body.get("key"))
                    save_store(store)
                except adapters.AdapterError as e:
                    return self._send_json({"error": str(e)}, 400)
            return self._send_json(r)
        if method == "POST" and path == "/api/oauth/deliver":
            with _lock:
                try:
                    r = adapters.oauth.deliver(store, body.get("did"), body.get("key"),
                                               {"text": body.get("text", "")})
                    save_store(store)
                except adapters.AdapterError as e:
                    return self._send_json({"error": str(e)}, 400)
            return self._send_json(r)
        if method == "GET" and path == "/api/oauth/rate":
            did = (qs.get("did") or [None])[0]
            key = (qs.get("key") or [None])[0]
            if not did or key not in adapters.oauth.adapters:
                return self._send_json({"error": "参数不足"}, 400)
            return self._send_json(adapters.oauth.rate_usage(store, did, key))

        # ===== 联邦协议 =====
        fed = federation.Federation(BASE_URL, store)
        if method == "GET" and path == "/api/federation/stats":
            return self._send_json(fed.stats())
        if method == "GET" and path == "/api/federation/actors":
            return self._send_json([
                fed.actor(d, (find_user(store, d) or {}).get("name")) for d in store.get("ap_users", [])
            ])
        if method == "GET" and path == "/api/federation/activities":
            return self._send_json(list(reversed(store.get("ap_activities", [])))[:60])
        if method == "POST" and path == "/api/federation/follow":
            with _lock:
                r = fed.follow(body.get("follower"), body.get("target"))
                save_store(store)
            return self._send_json(r, 201)
        if method == "POST" and path == "/api/federation/unfollow":
            with _lock:
                r = fed.unfollow(body.get("follower"), body.get("target"))
                save_store(store)
            return self._send_json(r)
        if method == "POST" and path == "/api/federation/announce":
            product = find_product(store, body.get("product_id"))
            if not product:
                return self._send_json({"error": "商品不存在"}, 400)
            with _lock:
                r = fed.announce_product(body.get("actor"), product)
                save_store(store)
            return self._send_json(r, 201)
        m = re.match(r"^/api/federation/inbox/([^/]+)$", path)
        if method == "GET" and m:
            return self._send_json(fed.inbox(m.group(1)))
        m = re.match(r"^/api/federation/outbox/([^/]+)$", path)
        if method == "GET" and m:
            return self._send_json(fed.outbox(m.group(1)))
        m = re.match(r"^/api/federation/followers/([^/]+)$", path)
        if method == "GET" and m:
            return self._send_json(fed.followers(m.group(1)))

        # ===== 端侧推荐 / 联邦聚合 =====
        if method == "GET" and path == "/api/fl/params":
            return self._send_json(federated_rec.model_params(store))
        if method == "GET" and path == "/api/fl/stats":
            return self._send_json(federated_rec.stats(store))
        if method == "POST" and path == "/api/fl/report":
            with _lock:
                r = federated_rec.report_update(store, body)
                save_store(store)
            return self._send_json(r, 201)
        if method == "POST" and path == "/api/fl/aggregate":
            with _lock:
                r = federated_rec.aggregate(store)
                save_store(store)
            return self._send_json(r)

        # ===== 病毒增长：成绩单 / 邀请追踪 / 模板复刻 =====
        if method == "POST" and path == "/api/share/scorecard":
            did = body.get("did")
            user = find_user(store, did)
            if not user:
                return self._send_json({"error": "用户不存在"}, 404)
            camp = next((c for c in store["campaigns"] if c["id"] == body.get("campaign_id")), None)
            with _lock:
                result = growth.create_scorecard(
                    store, did, user["name"], camp, get_stats(store),
                    federation.Federation(BASE_URL, store).stats(), BASE_URL)
                save_store(store)
            return self._send_json(result, 201)
        if method == "GET" and path == "/api/share/scorecard":
            code = (qs.get("code") or [None])[0]
            share = growth.find_share(store, code)
            if not share:
                return self._send_json({"error": "分享不存在"}, 404)
            with _lock:
                growth.record_view(store, code, (qs.get("visitor") or [None])[0])
                save_store(store)
            return self._send_json(share)
        if method == "POST" and path == "/api/invite/convert":
            code = body.get("code")
            if not code:
                return self._send_json({"error": "缺少邀请码"}, 400)
            with _lock:
                growth.record_conversion(store, code, body.get("did"), body.get("visitor"))
                save_store(store)
            return self._send_json({"ok": True, "code": code})
        if method == "POST" and path == "/api/templates":
            did = body.get("did")
            camp = next((c for c in store["campaigns"] if c["id"] == body.get("campaign_id")), None)
            product = find_product(store, body.get("product_id"))
            if not camp or not product:
                return self._send_json({"error": "活动或商品不存在"}, 400)
            with _lock:
                result = growth.create_template(store, did, camp, product,
                                                body.get("name") or (product["title"] + " · 一键复刻模板"),
                                                BASE_URL)
                save_store(store)
            return self._send_json(result, 201)
        if method == "GET" and path == "/api/templates":
            return self._send_json(list(reversed(store.get("templates", []))))
        if method == "POST" and path == "/api/templates/clone":
            code = body.get("code")
            tpl = growth.find_template(store, code)
            if not tpl:
                return self._send_json({"error": "模板不存在"}, 404)
            product = find_product(store, tpl["product_id"])
            if not product:
                return self._send_json({"error": "模板商品不存在"}, 404)
            with _lock:
                tpl["clones"] += 1
                # 复刻 = 以模板的商品与通道重新发起一次合规分发
                camp = {"id": newid("c"), "name": "复刻 · " + tpl["name"], "product_id": product["id"],
                        "channel": tpl["channel"], "created_at": now(), "sent": 0}
                sent = 0
                for u in store["users"]:
                    sc, matched = score_product(u, product, store)
                    if not matched:
                        continue
                    ok, _ = has_consent(store, u, tpl["channel"])
                    if not ok:
                        continue
                    add_event(store, "impression", u["did"], product["id"], camp["id"], tpl["channel"],
                              {"matched": matched, "clone_of": code})
                    sent += 1
                camp["sent"] = sent
                store["campaigns"].append(camp)
                growth.add_event(store, "template_clone", code, body.get("did"), {"campaign_id": camp["id"]})
                save_store(store)
            return self._send_json({"campaign": camp, "sent": sent, "template": tpl}, 201)
        if method == "GET" and path == "/api/growth":
            return self._send_json(growth.growth_stats(store))

        # 数据
        if method == "GET" and path == "/api/events":
            limit = int((qs.get("limit") or ["50"])[0])
            return self._send_json(list(reversed(store["events"]))[:limit])
        if method == "GET" and path == "/api/orders":
            return self._send_json(list(reversed(store["orders"])))
        if method == "GET" and path == "/api/stats":
            return self._send_json(get_stats(store))

        return self._send_json({"error": "接口不存在: " + path}, 404)

    def _handle(self, method):
        path, qs, body = self._parse()
        ip = self.client_address[0] if self.client_address else "unknown"

        # 健康检查（供 PaaS / 容器探针使用）
        if path in ("/api/health", "/health"):
            return self._send_json({"status": "ok", "env": config.ENV, "time": now()})

        # 限流
        if not rate_allowed(ip):
            return self._send_json({"error": "请求过于频繁，请稍后再试"}, 429)

        # 写操作管理令牌保护：公开传播类接口放行，管理类写操作需令牌
        PUBLIC_WRITES = {"/api/invite/convert", "/api/templates/clone", "/api/share/scorecard"}
        if config.ADMIN_TOKEN and method in ("POST", "PUT") and path not in PUBLIC_WRITES:
            supplied = self.headers.get("X-Admin-Token", "")
            if supplied != config.ADMIN_TOKEN:
                return self._send_json({"error": "需要有效的管理令牌"}, 403)

        if path.startswith("/api/"):
            try:
                self._api(method, path, qs, body)
            except Exception as e:
                if config.DEBUG:
                    self._send_json({"error": "服务端错误", "detail": str(e)}, 500)
                else:
                    self._send_json({"error": "服务端错误"}, 500)
        elif path.startswith("/.well-known/") or path.startswith("/ap/"):
            try:
                self._activitypub(method, path, qs, body)
            except Exception as e:
                if config.DEBUG:
                    self._send_json({"error": "服务端错误", "detail": str(e)}, 500)
                else:
                    self._send_json({"error": "服务端错误"}, 500)
        else:
            self._static(path)

    def _activitypub(self, method, path, qs, body):
        store = load_store()
        fed = federation.Federation(BASE_URL, store)
        if path == "/.well-known/webfinger":
            resource = (qs.get("resource") or [""])[0]
            uid = resource.replace("acct:", "").split("@")[0].split(":")[-1]
            did = next((d for d in store.get("ap_users", []) if d.split(":")[-1] == uid), None)
            if not did:
                return self._send_json({"error": "not found"}, 404)
            return self._send_json(fed.webfinger(did))
        m = re.match(r"^/ap/actor/([^/]+)(?:/(inbox|outbox|followers))?$", path)
        if m:
            did, sub = m.group(1), m.group(2)
            if method == "GET":
                if sub == "inbox":
                    return self._send_json(fed.inbox(did))
                if sub == "outbox":
                    return self._send_json(fed.outbox(did))
                if sub == "followers":
                    return self._send_json(fed.followers(did))
                return self._send_json(fed.actor(did, (find_user(store, did) or {}).get("name")))
            if method == "POST" and sub == "inbox":
                with _lock:
                    r = fed.handle_inbox(did, body)
                    save_store(store)
                return self._send_json(r, 202)
        if path == "/ap/inbox" and method == "POST":
            did = (store.get("ap_users") or [None])[0]
            if not did:
                return self._send_json({"error": "no actors"}, 404)
            with _lock:
                r = fed.handle_inbox(did, body)
                save_store(store)
            return self._send_json(r, 202)
        return self._send_json({"error": "not found"}, 404)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,PUT,OPTIONS")
        self.end_headers()


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(STORE_PATH):
        store = empty_store()
        seed(store, BASE_URL)
        save_store(store)
    port = PORT
    httpd = ThreadingHTTPServer((config.HOST, port), Handler)
    print("DTC MVP 已启动: %s (env=%s, base=%s)" % (
        config.BASE_URL, config.ENV, BASE_URL), flush=True)
    print("数据目录: %s" % DATA_DIR, flush=True)
    print("按 Ctrl+C 停止", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
        httpd.server_close()


if __name__ == "__main__":
    main()
