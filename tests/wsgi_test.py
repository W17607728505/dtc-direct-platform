# -*- coding: utf-8 -*-
"""WSGI 模式端到端测试：直接调用 application()，不经过 socket"""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 用独立测试目录，避免污染运行数据
TEST_DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_wsgi_testdata")
os.environ["DTC_DATA_DIR"] = TEST_DATA

import config  # noqa: E402  必须在设置环境变量后导入
import server as srv  # noqa: E402
from wsgi_app import application  # noqa: E402

# 让 server 模块使用测试目录
srv.DATA_DIR = config.DATA_DIR
srv.STORE_PATH = config.STORE_PATH
srv.BASE_URL = "https://demo.pythonanywhere.com"
srv.federation.Federation  # noqa

passed = 0


def check(cond, msg):
    global passed
    assert cond, "FAIL: " + msg
    passed += 1
    print("  PASS  " + msg)


def request(method, path, body=None, query=""):
    captured = {}

    def start_response(status, headers):
        captured["status"] = status
        captured["headers"] = headers

    raw = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else b""
    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "CONTENT_TYPE": "application/json",
        "CONTENT_LENGTH": str(len(raw)),
        "wsgi.input": io.BytesIO(raw),
    }
    chunks = application(environ, start_response)
    data = b"".join(chunks)
    ctype = dict(captured.get("headers", [])).get("Content-Type", "")
    if "json" in ctype:
        captured["body"] = json.loads(data.decode("utf-8")) if data else {}
    else:
        captured["body"] = data
    return captured


def main():
    print("== WSGI 模式端到端测试 ==")
    import shutil
    if os.path.exists(TEST_DATA):
        shutil.rmtree(TEST_DATA)
    fresh = srv.empty_store()
    srv.seed(fresh, srv.BASE_URL)
    srv.save_store(fresh)

    r = request("GET", "/api/health")
    check(r["status"].startswith("200"), "健康检查 200")

    r = request("GET", "/api/stats")
    check(r["body"]["users"] == 4, "GET /api/stats 正常（种子 4 用户）")

    r = request("GET", "/", query="")
    check(r["status"].startswith("200") and b"DTC" in r["body"], "根路径返回首页 HTML")

    r = request("GET", "/api/recommendations", query="did=did:dtc:u1")
    check(len(r["body"]) > 0, "兴趣匹配推荐正常")

    r = request("POST", "/api/campaigns", {"product_id": "p1", "channel": "inbox"})
    check(r["body"]["sent"] >= 1, "POST 分发正常（触达 >=1）")
    cid = r["body"]["campaign"]["id"]

    r = request("POST", "/api/share/scorecard", {"did": "did:dtc:u1", "campaign_id": cid})
    check(len(r["body"]["code"]) == 6, "成绩单生成正常")

    r = request("POST", "/api/templates", {"did": "did:dtc:u1", "campaign_id": cid, "product_id": "p1"})
    tcode = r["body"]["code"]
    check(len(tcode) == 6, "模板发布正常")

    r = request("POST", "/api/templates/clone", {"code": tcode, "did": "did:dtc:u2"})
    check("campaign" in r["body"], "模板一键复刻正常")

    r = request("GET", "/api/growth")
    check(r["body"]["k_factor"] >= 0, "增长指标正常")

    r = request("GET", "/.well-known/webfinger", query="resource=acct:u1@dtc.local")
    check("links" in r["body"], "WebFinger 联邦协议正常")

    r = request("GET", "/api/fl/params")
    check("tag_weights" in r["body"], "联邦学习参数下发正常")

    r = request("GET", "/api/adapters")
    check(len(r["body"]) == 4, "社媒适配器列表正常")

    print("\n== WSGI 全部 %d 项通过 ==" % passed)

    if os.path.exists(TEST_DATA):
        shutil.rmtree(TEST_DATA)


if __name__ == "__main__":
    main()
