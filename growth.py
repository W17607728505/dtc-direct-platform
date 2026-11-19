# -*- coding: utf-8 -*-
"""
病毒式增长模块
- 成绩单分享：把真实触达成效变成可传播的社交货币
- 邀请来源追踪：share_created / invite_visit / invite_convert 漏斗
- 活动模板一键复刻：新用户零门槛复现核心体验
"""
import secrets
import string
from datetime import datetime, timezone


def iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def short_code(n=6):
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


def newid(prefix):
    return "%s_%s" % (prefix, secrets.token_hex(5))


def add_event(store, etype, code=None, did=None, meta=None, visitor=None):
    ev = {"id": newid("g"), "type": etype, "code": code, "did": did, "ts": iso()}
    if visitor:
        ev["visitor"] = visitor
    if meta:
        ev["meta"] = meta
    store.setdefault("invites", []).append(ev)
    return ev


def create_scorecard(store, did, name, campaign, stats, fed_stats, base_url):
    """生成成绩单分享：内容来自真实成效数据"""
    code = short_code()
    touch = campaign["sent"] if campaign else stats["funnel"]["impression"]
    funnel = stats["funnel"]
    card = {
        "headline": "我用 DTC 直达了 %d 人" % touch,
        "owner": name,
        "touch": touch,
        "impression": funnel["impression"],
        "click": funnel["click"],
        "purchase": funnel["purchase"],
        "conversion_rate": stats["conversion_rate"],
        "creator_payout": stats["creator_payout"],
        "compliant_note": "无授权不发送 · 兴趣不匹配不发送 · 超频不发送",
        "fed_follows": fed_stats.get("follows", 0),
    }
    share = {
        "code": code, "type": "scorecard", "owner": did,
        "campaign_id": campaign["id"] if campaign else None,
        "card": card, "created_at": iso(), "views": 0, "conversions": 0,
    }
    store.setdefault("shares", []).append(share)
    add_event(store, "share_created", code, did, {"type": "scorecard"})
    return {"code": code, "url": base_url + "/?invite=" + code, "card": card}


def create_template(store, did, campaign, product, name, base_url):
    code = short_code()
    tpl = {
        "code": code, "owner": did, "name": name,
        "product_id": product["id"], "channel": campaign["channel"],
        "created_at": iso(), "clones": 0,
    }
    store.setdefault("templates", []).append(tpl)
    add_event(store, "template_created", code, did, {"product_id": product["id"]})
    return {"code": code, "url": base_url + "/?template=" + code, "template": public_template(tpl)}


def public_template(tpl):
    return {k: v for k, v in tpl.items()}


def find_share(store, code):
    return next((s for s in store.get("shares", []) if s["code"] == code), None)


def find_template(store, code):
    return next((t for t in store.get("templates", []) if t["code"] == code), None)


def record_view(store, code, visitor=None):
    share = find_share(store, code)
    if share:
        share["views"] += 1
    add_event(store, "invite_visit", code, share["owner"] if share else None, visitor=visitor)
    return share


def record_conversion(store, code, did, visitor=None):
    share = find_share(store, code)
    if share:
        share["conversions"] += 1
    add_event(store, "invite_convert", code, did or (share["owner"] if share else None), visitor=visitor)
    return share


def growth_stats(store):
    events = store.get("invites", [])
    shares = store.get("shares", [])
    templates = store.get("templates", [])
    funnel = {t: sum(1 for e in events if e["type"] == t)
              for t in ("share_created", "invite_visit", "invite_convert", "template_created", "template_clone")}
    sharers = len({e["did"] for e in events if e["type"] == "share_created" and e.get("did")})
    invites_per_user = funnel["share_created"] / sharers if sharers else float(funnel["share_created"])
    visit_to_convert = funnel["invite_convert"] / funnel["invite_visit"] if funnel["invite_visit"] else 0
    k_factor = round(invites_per_user * visit_to_convert, 2)
    return {
        "k_factor": k_factor,
        "formula": "K = 人均分享数 × 访问转化率",
        "invites_per_user": round(invites_per_user, 2),
        "visit_to_convert": round(visit_to_convert, 2),
        "funnel": funnel,
        "shares": len(shares),
        "templates": len(templates),
        "total_share_views": sum(s.get("views", 0) for s in shares),
        "total_conversions": sum(s.get("conversions", 0) for s in shares),
        "total_clones": sum(t.get("clones", 0) for t in templates),
        "recent_events": list(reversed(events))[:14],
        "top_shares": sorted(shares, key=lambda s: -s.get("views", 0))[:5],
    }
