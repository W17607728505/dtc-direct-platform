# -*- coding: utf-8 -*-
"""
联邦协议层：ActivityPub 风格的去中心化触达
- 用户关注创作者 Actor，商品发布作为 Create/Announce 活动投递到订阅者 inbox
- 触达不依赖社媒中介：Follow / Accept / Create / Announce 全部走开放协议
"""
import json
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

AS = "https://www.w3.org/ns/activitystreams"
PUBLIC = AS + "#Public"


def iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Federation:
    def __init__(self, base_url, store):
        self.base = base_url.rstrip("/")
        self.store = store

    # ---------- Actor / WebFinger ----------
    def actor_id(self, did):
        return self.base + "/ap/actor/" + urllib.parse.quote(did, safe="")

    def actor(self, did, name=None):
        uid = did.split(":")[-1]
        return {
            "@context": [AS, {"@language": "zh"}], "id": self.actor_id(did),
            "type": "Person", "name": name or uid, "preferredUsername": uid,
            "inbox": self.actor_id(did) + "/inbox",
            "outbox": self.actor_id(did) + "/outbox",
            "followers": self.actor_id(did) + "/followers",
            "following": self.actor_id(did) + "/following",
            "endpoints": {"sharedInbox": self.base + "/ap/inbox"},
            "discoverable": True, "manuallyApprovesFollowers": False,
        }

    def webfinger(self, did):
        uid = did.split(":")[-1]
        return {
            "subject": "acct:%s@dtc.local" % uid,
            "links": [{"rel": "self", "type": "application/activity+json", "href": self.actor_id(did)}],
        }

    def did_from_actor(self, actor_id):
        if not actor_id or "/ap/actor/" not in actor_id:
            return None
        try:
            return urllib.parse.unquote(actor_id.split("/ap/actor/")[-1].split("/")[0])
        except Exception:
            return None

    # ---------- 活动构造 ----------
    def new_activity(self, atype, actor_did, obj, to=None):
        return {
            "@context": AS, "id": self.base + "/ap/activity/" + uuid.uuid4().hex[:12],
            "type": atype, "actor": self.actor_id(actor_did), "published": iso(),
            "to": to or [PUBLIC], "object": obj,
        }

    def product_note(self, product):
        return {
            "type": "Note", "name": product.get("title", ""),
            "content": product.get("desc", ""),
            "attachment": [{"type": "PropertyValue", "name": "price", "value": str(product.get("price", 0))}],
            "tag": [{"type": "Hashtag", "name": "#" + t} for t in product.get("tags", [])],
        }

    # ---------- 集合 ----------
    def _actors(self, did):
        return self.store.setdefault("ap_actors", {})

    def outbox(self, did):
        items = [a for a in self.store.get("ap_activities", [])
                 if a.get("actor") == self.actor_id(did)]
        return {"@context": AS, "id": self.actor_id(did) + "/outbox", "type": "OrderedCollection",
                "totalItems": len(items), "orderedItems": list(reversed(items))}

    def inbox(self, did):
        items = self.store.get("ap_inbox", {}).get(did, [])
        return {"@context": AS, "id": self.actor_id(did) + "/inbox", "type": "OrderedCollection",
                "totalItems": len(items), "orderedItems": list(reversed(items))}

    def followers(self, did):
        f = [x for x in self.store.get("ap_follows", [])
             if x["following"] == did and x["state"] == "accepted"]
        return {"@context": AS, "id": self.actor_id(did) + "/followers", "type": "OrderedCollection",
                "totalItems": len(f), "orderedItems": [self.actor_id(x["follower"]) for x in f]}

    def follower_dids(self, did):
        return [x["follower"] for x in self.store.get("ap_follows", [])
                if x["following"] == did and x["state"] == "accepted"]

    def following_dids(self, did):
        return [x["following"] for x in self.store.get("ap_follows", [])
                if x["follower"] == did and x["state"] == "accepted"]

    # ---------- 投递 ----------
    def deliver_activity(self, target_did, activity):
        self.store.setdefault("ap_inbox", {}).setdefault(target_did, []).append(activity)
        return {"local": True, "target": target_did}

    def follow(self, follower_did, target_did):
        act = self.new_activity("Follow", follower_did, self.actor_id(target_did),
                                to=[self.actor_id(target_did)])
        self.store.setdefault("ap_activities", []).append(act)
        self.store.setdefault("ap_follows", []).append({
            "id": uuid.uuid4().hex[:10], "follower": follower_did, "following": target_did,
            "state": "pending", "ts": iso(),
        })
        self.deliver_activity(target_did, act)
        # 目标自动接受（manuallyApprovesFollowers=False）
        accept = self.new_activity("Accept", target_did, act, to=[self.actor_id(follower_did)])
        self.store["ap_activities"].append(accept)
        self.deliver_activity(follower_did, accept)
        for f in self.store["ap_follows"]:
            if f["follower"] == follower_did and f["following"] == target_did:
                f["state"] = "accepted"
        return {"follow": act, "accept": accept}

    def unfollow(self, follower_did, target_did):
        act = self.new_activity("Undo", follower_did,
                                {"type": "Follow", "actor": self.actor_id(follower_did),
                                 "object": self.actor_id(target_did)}, to=[self.actor_id(target_did)])
        self.store.setdefault("ap_activities", []).append(act)
        self.store["ap_follows"] = [f for f in self.store.get("ap_follows", [])
                                    if not (f["follower"] == follower_did and f["following"] == target_did)]
        self.deliver_activity(target_did, act)
        return act

    def announce_product(self, did, product):
        """商品发布作为 Create 活动写入 outbox，并广播给所有 follower 的 inbox"""
        act = self.new_activity("Create", did, self.product_note(product))
        self.store.setdefault("ap_activities", []).append(act)
        targets = self.follower_dids(did)
        for t in targets:
            self.deliver_activity(t, act)
        return {"activity": act, "delivered": len(targets), "targets": targets}

    def handle_inbox(self, did, activity):
        """接收外部活动：Follow 自动 Accept；Create/Announce 存入本地 inbox"""
        t = activity.get("type")
        self.store.setdefault("ap_inbox", {}).setdefault(did, []).append(activity)
        if t == "Follow":
            accept = self.new_activity("Accept", did, activity, to=[activity.get("actor")])
            self.store.setdefault("ap_activities", []).append(accept)
            follower = self.did_from_actor(activity.get("actor"))
            if follower:
                self.deliver_activity(follower, accept)
                self.store.setdefault("ap_follows", []).append({
                    "id": uuid.uuid4().hex[:10], "follower": follower, "following": did,
                    "state": "accepted", "ts": iso(),
                })
            return {"accepted": True, "activity": accept}
        return {"received": True, "type": t}

    def stats(self):
        acts = self.store.get("ap_activities", [])
        inbox = self.store.get("ap_inbox", {})
        follows = self.store.get("ap_follows", [])
        return {
            "actors": len(self.store.get("ap_users", [])),
            "activities": len(acts),
            "follows": sum(1 for f in follows if f["state"] == "accepted"),
            "inbox_items": sum(len(v) for v in inbox.values()),
            "activity_types": {t: sum(1 for a in acts if a.get("type") == t)
                               for t in sorted({a.get("type") for a in acts})},
        }


def seed_federation(store, base_url):
    """为演示种子用户生成 Actor 与初始联邦关系"""
    fed = Federation(base_url, store)
    users = store.get("users", [])
    if not users:
        return
    store["ap_users"] = [u["did"] for u in users]
    store.setdefault("ap_actors", {})
    for u in users:
        store["ap_actors"][u["did"]] = fed.actor(u["did"], u["name"])
    # 创作者 u1 有两个关注者；发布一个商品 Create 活动
    fed.follow("did:dtc:u2", "did:dtc:u1")
    fed.follow("did:dtc:u3", "did:dtc:u1")
    fed.announce_product("did:dtc:u1", store["products"][0])
