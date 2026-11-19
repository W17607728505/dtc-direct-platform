# -*- coding: utf-8 -*-
"""DTC MVP 端到端冒烟测试：覆盖 授权 -> 发布 -> 匹配 -> 分发 -> 点击 -> 成交 -> 分账"""
import json
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8787"


def req(path, method="GET", data=None):
    raw = json.dumps(data, ensure_ascii=False).encode("utf-8") if data is not None else None
    r = urllib.request.Request(BASE + path, data=raw, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(cond, msg):
    assert cond, "FAIL: " + msg
    print("  PASS  " + msg)


def main():
    print("== DTC MVP 冒烟测试 ==")
    req("/api/reset", "POST", {})
    s0 = req("/api/stats")
    check(s0["users"] == 4, "种子数据：4 个用户")
    check(s0["products"] == 5, "种子数据：5 个商品")

    # 用户 + 同意账本
    u = req("/api/users", "POST", {"name": "测试用户", "interests": ["AI", "设计"]})
    check(u["did"].startswith("did:dtc:"), "创建用户并生成 DID")
    u = req("/api/users/" + urllib.parse.quote(u["did"], safe="") + "/consents", "PUT",
            {"channel": "email", "enabled": True, "max_per_week": 3})
    check(u["consents"]["email"]["enabled"] is True, "同意账本：开启邮件通道")

    # 商品发布
    p = req("/api/products", "POST", {"title": "测试商品", "price": 50,
            "tags": ["AI", "效率工具"], "desc": "冒烟测试商品", "owner": "测试"})
    check(p["id"].startswith("p_"), "发布商品进入统一目录")

    # 精准匹配
    recs = req("/api/recommendations?did=" + urllib.parse.quote(u["did"], safe=""))
    check(any(r["id"] == p["id"] for r in recs), "兴趣匹配推荐命中新商品")
    check("AI" in recs[0]["matched"], "推荐返回匹配标签")

    # 分发（合规拦截验证：关闭邮件 + 大量频次 -> 应被拦截）
    req("/api/users/" + urllib.parse.quote(u["did"], safe="") + "/consents", "PUT",
        {"channel": "inbox", "enabled": False, "max_per_week": 3})
    r1 = req("/api/campaigns", "POST", {"product_id": p["id"], "channel": "inbox"})
    check(r1["sent"] >= 1, "inbox 分发触达已授权且匹配的用户")
    check(r1["skipped"]["no_consent"] >= 1, "未授权用户被合规拦截")

    # 点击 + 成交
    imps = [e for e in req("/api/events?limit=300")
            if e["type"] == "impression" and e["campaign_id"] == r1["campaign"]["id"]]
    target = imps[0]
    req("/api/click", "POST", {"did": target["did"], "product_id": p["id"],
        "campaign_id": r1["campaign"]["id"], "channel": "inbox"})
    order = req("/api/purchase", "POST", {"did": target["did"], "product_id": p["id"],
        "campaign_id": r1["campaign"]["id"], "channel": "inbox"})
    check(order["amount"] == 50, "成交生成订单并计价")

    s1 = req("/api/stats")
    check(s1["funnel"]["impression"] > s0["funnel"]["impression"], "曝光计入统计")
    check(s1["funnel"]["click"] > s0["funnel"]["click"], "点击计入统计")
    check(s1["funnel"]["purchase"] > s0["funnel"]["purchase"], "成交计入统计")
    check(s1["gmv"] >= s0["gmv"] + 50, "GMV 累加")
    check(abs(s1["platform_fee"] - round(s1["gmv"] * 0.1, 2)) < 0.01, "平台分账计算正确")

    # 静态页面
    with urllib.request.urlopen(BASE + "/") as resp:
        html = resp.read().decode("utf-8")
    check("DTC 直达平台" in html, "前端页面可访问")

    req("/api/reset", "POST", {})
    print("== 全部通过 ==")


if __name__ == "__main__":
    main()
