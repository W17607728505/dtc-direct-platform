# -*- coding: utf-8 -*-
"""
端侧推荐 + 联邦聚合（服务端部分）
- 服务端只下发模型参数与商品向量，原始兴趣数据不出端
- 端侧本地推理（见 public/ondevice.js），上报经差分隐私加噪的聚合统计
- 服务端用 FedAvg 聚合多端更新，不接触任何个人原始数据
"""
import hashlib
import json
import uuid
from collections import Counter
from datetime import datetime, timezone


def iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def model_params(store):
    model = store.setdefault("fl_model", {
        "version": 1, "rounds": 0, "epsilon": 1.0, "tag_weights": {},
    })
    vocab = sorted({t for p in store.get("products", []) for t in p.get("tags", [])})
    weights = {t: round(float(model["tag_weights"].get(t, 1.0)), 3) for t in vocab}
    popularity = {}
    for e in store.get("events", []):
        if e.get("type") in ("click", "purchase") and e.get("product_id"):
            popularity[e["product_id"]] = popularity.get(e["product_id"], 0) + 1
    return {
        "version": model["version"], "rounds": model["rounds"],
        "tag_vocab": vocab, "tag_weights": weights, "popularity": popularity,
        "privacy": {
            "mechanism": "laplace", "epsilon": model.get("epsilon", 1.0),
            "note": "端侧本地加噪，仅上报聚合统计；原始兴趣与行为不出端",
        },
    }


def report_update(store, update):
    """接收端侧加噪统计；只存匿名哈希，不存明文 DID"""
    did = update.get("did", "")
    hashed = hashlib.sha256(("dtc-fl:" + did).encode("utf-8")).hexdigest()[:16]
    rec = {
        "id": uuid.uuid4().hex[:10], "ts": iso(), "client_hash": hashed,
        "tag_counts": {str(k): float(v) for k, v in (update.get("tag_counts") or {}).items()},
        "client_version": update.get("client_version"),
        "epsilon": update.get("epsilon"),
    }
    store.setdefault("fl_updates", []).append(rec)
    return {"accepted": True, "pending": len(store["fl_updates"]), "client_hash": hashed}


def aggregate(store):
    """FedAvg：对各端的加噪统计做加权平均并裁剪，更新全局标签权重"""
    updates = store.get("fl_updates", [])
    if not updates:
        return {"aggregated": 0, "version": store.get("fl_model", {}).get("version", 1), "message": "无待聚合更新"}
    model = store.setdefault("fl_model", {"version": 1, "rounds": 0, "epsilon": 1.0, "tag_weights": {}})
    acc, n = Counter(), 0
    for u in updates:
        for tag, count in u.get("tag_counts", {}).items():
            acc[tag] += max(0.0, float(count))
        n += 1
    for tag, total in acc.items():
        avg = total / n
        old = float(model["tag_weights"].get(tag, 1.0))
        clipped = max(0.5, min(2.5, avg))
        model["tag_weights"][tag] = round(0.7 * old + 0.3 * clipped, 3)
    model["version"] += 1
    model["rounds"] += 1
    store["fl_updates"] = []
    return {"aggregated": n, "version": model["version"], "rounds": model["rounds"],
            "tag_weights": model["tag_weights"]}


def stats(store):
    model = store.get("fl_model", {})
    return {
        "version": model.get("version", 1), "rounds": model.get("rounds", 0),
        "pending_updates": len(store.get("fl_updates", [])),
        "epsilon": model.get("epsilon", 1.0),
        "tag_weights": model.get("tag_weights", {}),
        "privacy": "端侧推理 + 本地差分隐私 + 服务端 FedAvg 聚合，原始数据不出端",
    }
