# -*- coding: utf-8 -*-
"""阶段二端到端测试：社媒 OAuth 适配器 / 联邦协议 / 端侧推荐与联邦聚合"""
import json
import urllib.error
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
    print("== 阶段二能力测试 ==")
    req("/api/reset", "POST", {})

    # ---------- 社媒适配器 / OAuth2 ----------
    adapters = req("/api/adapters")
    check(len(adapters) == 4, "4 个社媒适配器（Telegram/微信/Meta/X）")
    check(all(a["sandbox"] for a in adapters), "未配置凭证时全部进入沙箱模式")
    check(all(a["scopes"] and a["rate_limit"] for a in adapters), "每个适配器声明最小 Scope 与速率限制")

    start = req("/api/oauth/start", "POST", {"key": "telegram", "did": "did:dtc:u1"})
    check(bool(start["state"]) and "authorize_url" in start, "OAuth 授权请求含一次性 state 与授权 URL")
    try:
        req("/api/oauth/callback", "POST", {"key": "telegram", "code": "x", "state": "bad-state"})
        check(False, "错误 state 应被拒绝")
    except urllib.error.HTTPError as e:
        check(e.code == 400, "错误 state 被拒绝（防 CSRF）")

    conn = req("/api/oauth/callback", "POST",
               {"key": "telegram", "code": "demo-code", "state": start["state"]})
    check(conn["sandbox"] and conn["adapter"] == "telegram", "沙箱 OAuth 授权完成")
    check("token_masked" in conn and "access_token" not in conn, "令牌脱敏，不以明文下发")
    conns = req("/api/oauth/connections?did=did:dtc:u1")
    check(len(conns) == 1, "授权连接已持久化")

    delivered = req("/api/oauth/deliver", "POST",
                    {"did": "did:dtc:u1", "key": "telegram", "text": "hello"})
    check(delivered["ok"] and delivered["sandbox"], "沙箱投递成功并标注非真实")
    check(delivered["rate_usage"]["minute"] == 1, "适配器速率限制计数生效")
    rate = req("/api/oauth/rate?did=did:dtc:u1&key=telegram")
    check(rate["minute"] == 1 and rate["limit"]["minute"] == 30, "速率余量可查询")

    req("/api/oauth/revoke", "POST", {"did": "did:dtc:u1", "key": "telegram"})
    check(len(req("/api/oauth/connections?did=did:dtc:u1")) == 0, "授权可撤销")

    # ---------- 联邦协议 ----------
    fs = req("/api/federation/stats")
    check(fs["actors"] == 4, "种子数据生成 4 个 Actor")
    check(fs["follows"] == 2, "初始有 2 个有效关注关系")
    actors = req("/api/federation/actors")
    check(len(actors) == 4 and "inbox" in actors[0] and "outbox" in actors[0], "Actor 文档含 inbox/outbox")

    wf = req("/.well-known/webfinger?resource=acct:u1@dtc.local")
    check("links" in wf and wf["links"][0]["rel"] == "self", "WebFinger 发现协议可用")
    actor_path = urllib.parse.urlparse(wf["links"][0]["href"]).path
    actor_doc = req(actor_path)
    check(actor_doc["type"] == "Person", "标准 Actor 文档可通过协议端点访问")
    ob = req(actor_path + "/outbox")
    check(ob["totalItems"] >= 1, "Outbox 含初始 Create 活动")

    fr = req("/api/federation/follow", "POST",
             {"follower": "did:dtc:u4", "target": "did:dtc:u3"})
    check(fr["accept"]["type"] == "Accept", "Follow 自动回 Accept")
    follow_inbox = req("/api/federation/inbox/did%3Adtc%3Au4")
    check(any(item["type"] == "Accept" for item in follow_inbox["orderedItems"]), "Accept 投递到关注者 inbox")

    an = req("/api/federation/announce", "POST", {"actor": "did:dtc:u1", "product_id": "p2"})
    check(an["delivered"] == 2, "商品广播投递到 u1 的 2 个关注者")
    inbox_u2 = req("/api/federation/inbox/did%3Adtc%3Au2")
    check(any(item["type"] == "Create" for item in inbox_u2["orderedItems"]), "Create 活动进入关注者收件箱")

    # ---------- 端侧推荐 / 联邦聚合 ----------
    params = req("/api/fl/params")
    check("tag_weights" in params and params["privacy"]["mechanism"] == "laplace", "模型参数与隐私机制下发")
    tag = params["tag_vocab"][0]
    for did in ["did:dtc:u1", "did:dtc:u2", "did:dtc:u3"]:
        req("/api/fl/report", "POST", {"did": did, "tag_counts": {tag: 1.3},
                                       "client_version": params["version"], "epsilon": 1.0})
    st = req("/api/fl/stats")
    check(st["pending_updates"] == 3, "端侧加噪上报已接收（3 条）")
    check(st["version"] == 1 and st["rounds"] == 0, "聚合前模型版本不变")
    ag = req("/api/fl/aggregate", "POST", {})
    check(ag["aggregated"] == 3 and ag["version"] == 2, "FedAvg 聚合升级模型到 v2")
    check(req("/api/fl/stats")["pending_updates"] == 0, "聚合后清空待处理队列")

    # ---------- 前端资源 ----------
    with urllib.request.urlopen(BASE + "/ondevice.js") as r:
        js = r.read().decode("utf-8")
    check("OnDevice" in js and "laplace" in js, "端侧推理引擎可访问")
    with urllib.request.urlopen(BASE + "/") as r:
        html = r.read().decode("utf-8")
    check("端侧推荐" in html and "联邦网络" in html and "通道集成" in html, "前端已挂载三个新视图入口")

    req("/api/reset", "POST", {})
    print("== 阶段二全部通过 ==")


if __name__ == "__main__":
    main()
