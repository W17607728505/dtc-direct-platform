# -*- coding: utf-8 -*-
"""
PythonAnywhere 部署助手
用法：python pa_deploy.py <用户名> <API_TOKEN> [step]
  step = check  : 验证 token 并列出已有 webapp
  step = create : 创建 webapp（默认域名 <username>.pythonanywhere.com）
  step = reload : 重载 webapp
仅使用标准库；token 只在命令行参数中传入，不写入任何文件。
"""
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

API = "https://www.pythonanywhere.com"


def call(path, token, method="GET", data=None):
    url = API + path
    raw = None
    if data is not None:
        raw = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=raw, method=method, headers={
        "Authorization": "Token " + token,
        "Content-Type": "application/json",
        "User-Agent": "dtc-deploy",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            body = r.read().decode("utf-8")
            return r.status, json.loads(body) if body else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        return e.code, {"error": body}


def main():
    if len(sys.argv) < 4:
        print("用法: python pa_deploy.py <用户名> <API_TOKEN> <check|create|reload>")
        sys.exit(1)
    user, token, step = sys.argv[1], sys.argv[2], sys.argv[3]
    base = "/api/v0/user/%s" % user

    if step == "check":
        code, res = call(base + "/webapps/", token)
        print("HTTP", code)
        if code == 200:
            print("webapps:", json.dumps(res, ensure_ascii=False, indent=2))
        else:
            print("error:", res)

    elif step == "create":
        domain = user + ".pythonanywhere.com"
        payload = {"domain_name": domain, "python_version": "python310"}
        code, res = call(base + "/webapps/", token, "POST", payload)
        print("HTTP", code)
        print(json.dumps(res, ensure_ascii=False, indent=2))
        if code in (200, 201):
            print("\n创建成功！域名:", domain)

    elif step == "reload":
        domain = user + ".pythonanywhere.com"
        code, res = call(base + "/webapps/%s/reload/" % domain, token, "POST", {})
        print("HTTP", code, res)

    else:
        print("未知步骤:", step)


if __name__ == "__main__":
    main()
