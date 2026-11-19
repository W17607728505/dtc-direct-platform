# -*- coding: utf-8 -*-
"""病毒增长端到端测试：成绩单 / 邀请来源埋点 / 模板复刻 / K 因子"""
import json
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
    print("== 病毒增长闭环测试 ==")
    req("/api/reset", "POST", {})
    g0 = req("/api/growth")
    check("k_factor" in g0 and "funnel" in g0, "增长指标接口可用")

    # 先做一次真实分发，产生可分享的活动
    camp = req("/api/campaigns", "POST", {"product_id": "p1", "channel": "inbox"})
    camp_id = camp["campaign"]["id"]

    # 1. 生成成绩单
    sc = req("/api/share/scorecard", "POST", {"did": "did:dtc:u1", "campaign_id": camp_id})
    check(len(sc["code"]) == 6 and "invite=" + sc["code"] in sc["url"], "成绩单生成含 6 位邀请码与分享链接")
    check(sc["card"]["headline"] and sc["card"]["creator_payout"] >= 0, "成绩单内容来自真实成效数据")
    check(sc["card"]["compliant_note"], "成绩单带合规说明")

    # 2. 好友通过邀请链接访问 -> 记录 visit
    visited = req("/api/share/scorecard?code=" + sc["code"] + "&visitor=visitor_test")
    check(visited["code"] == sc["code"], "邀请码可解析出原始成绩单")
    g1 = req("/api/growth")
    check(g1["funnel"]["share_created"] >= 1, "share_created 事件已埋点")
    check(g1["funnel"]["invite_visit"] >= 1, "invite_visit 事件已埋点")
    check(g1["total_share_views"] >= 1, "分享浏览量累加")

    # 3. 好友完成核心体验 -> 成交转化埋点
    req("/api/invite/convert", "POST", {"code": sc["code"], "did": "did:dtc:u2", "visitor": "visitor_test"})
    g2 = req("/api/growth")
    check(g2["funnel"]["invite_convert"] >= 1, "invite_convert 事件已埋点")
    check(g2["total_conversions"] >= 1, "转化数累加")
    check(g2["visit_to_convert"] > 0, "访问转化率已计算")
    check(g2["k_factor"] > g0["k_factor"], "K 因子随传播提升")

    # 4. 模板发布与一键复刻
    tpl = req("/api/templates", "POST", {"did": "did:dtc:u1", "campaign_id": camp_id, "product_id": "p1"})
    check(len(tpl["code"]) == 6 and "template=" + tpl["code"] in tpl["url"], "模板生成含专属模板码与链接")
    clone = req("/api/templates/clone", "POST", {"code": tpl["code"], "did": "did:dtc:u2"})
    check(clone["sent"] >= 0 and clone["campaign"]["name"].startswith("复刻"), "模板一键复刻生成新触达活动")
    g3 = req("/api/growth")
    check(g3["funnel"]["template_clone"] >= 1, "template_clone 事件已埋点")
    check(g3["total_clones"] >= 1, "模板复刻数累加")

    # 5. 事件流完整
    types = {e["type"] for e in g3["recent_events"]}
    check("share_created" in types and "invite_visit" in types, "邀请事件流包含分享与访问")

    req("/api/reset", "POST", {})
    print("== 病毒增长闭环全部通过 ==")


if __name__ == "__main__":
    main()
