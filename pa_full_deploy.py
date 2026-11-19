# -*- coding: utf-8 -*-
"""
PythonAnywhere 全自动部署脚本（仅标准库）
用法：python pa_full_deploy.py <用户名> <API_TOKEN> [check|deploy|status]

流程：
  check  - 验证 token、列出系统信息与已存在 webapp
  deploy - 上传全部项目文件 -> 写 WSGI 配置 -> 创建/配置 webapp -> reload
  status - 查看 webapp 配置与静态映射

token 只通过命令行参数传入，不写入任何文件。
"""
import json
import mimetypes
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

API = "https://www.pythonanywhere.com"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 不上传的目录/文件
SKIP_DIRS = {".git", "__pycache__", "data", "data_prodtest", "_wsgi_testdata", ".pytest_cache"}
SKIP_FILES = {".gitignore"}
UPLOAD_EXT = {".py", ".js", ".html", ".css", ".json", ".yaml", ".yml", ".txt", ".md",
              ".example", ".bat", ""}  # "" 表示无扩展名文件（如 Procfile）


def api(path, token, method="GET", data=None, multipart=None):
    url = API + path
    body = None
    headers = {
        "Authorization": "Token " + token,
        "User-Agent": "dtc-deploy",
    }
    if multipart is not None:
        field, filename, content = multipart
        boundary = "----dtc" + uuid.uuid4().hex
        body = (
            ("--%s\r\n" % boundary).encode()
            + ('Content-Disposition: form-data; name="%s"; filename="%s"\r\n' % (field, filename)).encode()
            + b"Content-Type: application/octet-stream\r\n\r\n"
            + content
            + ("\r\n--%s--\r\n" % boundary).encode()
        )
        headers["Content-Type"] = "multipart/form-data; boundary=" + boundary
    elif data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    last_err = None
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read().decode("utf-8")
                return r.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8", errors="replace")
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"detail": raw[:500]}
            return e.code, parsed
        except (TimeoutError, urllib.error.URLError, OSError) as e:
            last_err = e
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
    return 0, {"detail": "network error: %s" % last_err}


def collect_files():
    """收集需要上传的项目文件"""
    files = []
    for root, dirs, names in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for name in names:
            if name in SKIP_FILES:
                continue
            ext = os.path.splitext(name)[1].lower()
            if ext not in UPLOAD_EXT:
                continue
            full = os.path.join(root, name)
            rel = os.path.relpath(full, BASE_DIR).replace("\\", "/")
            files.append((rel, full))
    return files


def upload_files(user, token, project_home):
    files = collect_files()
    ok = fail = 0
    for i, (rel, full) in enumerate(files, 1):
        target = project_home + "/" + rel
        path = "/api/v0/user/%s/files/path%s" % (user, target)
        with open(full, "rb") as f:
            content = f.read()
        code, res = api(path, token, "POST", multipart=("content", rel, content))
        if code in (200, 201):
            ok += 1
        else:
            fail += 1
            print("  FAIL upload %s -> HTTP %s %s" % (rel, code, res))
        if i % 5 == 0 or i == len(files):
            print("  进度 %d/%d (成功 %d 失败 %d)" % (i, len(files), ok, fail), flush=True)
    print("  上传完成: 成功 %d, 失败 %d" % (ok, fail))
    return ok, fail


def write_wsgi(user, token, domain):
    """写 WSGI 配置文件到 /var/www/<user>_pythonanywhere_com.wsgi"""
    project_home = "/home/%s/dtc-direct-platform" % user
    wsgi_content = """import os
import sys

project_home = r'{home}'
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# 生产环境配置
os.environ['DTC_ENV'] = 'prod'
os.environ['DTC_BASE_URL'] = 'https://{domain}'
os.environ['HOST'] = '127.0.0.1'
os.environ['PORT'] = '8787'

from wsgi_app import application
""".format(home=project_home, domain=domain)
    wsgi_path = "/var/www/%s_pythonanywhere_com.wsgi" % user
    api_path = "/api/v0/user/%s/files/path%s" % (user, wsgi_path)
    code, res = api(api_path, token, "POST",
                    multipart=("content", "wsgi.py", wsgi_content.encode("utf-8")))
    print("  WSGI 配置写入: HTTP %s %s" % (code, "" if code in (200, 201) else res))
    return code in (200, 201)


def main():
    if len(sys.argv) < 4:
        print("用法: python pa_full_deploy.py <用户名> <API_TOKEN> <check|deploy|status>")
        sys.exit(1)
    user, token, step = sys.argv[1], sys.argv[2], sys.argv[3]
    domain = user + ".pythonanywhere.com"
    project_home = "/home/%s/dtc-direct-platform" % user
    base = "/api/v0/user/%s" % user

    if step == "check":
        code, res = api(base + "/webapps/", token)
        print("webapps HTTP", code, json.dumps(res, ensure_ascii=False))
        code2, info = api(base + "/system_image/", token)
        print("system_image HTTP", code2, json.dumps(info, ensure_ascii=False))
        code3, pyv = api(base + "/default_python3_version/", token)
        print("python3 version HTTP", code3, json.dumps(pyv, ensure_ascii=False))

    elif step == "deploy":
        print("=== 开始部署到 %s ===" % domain)
        print("[1/4] 上传项目文件...")
        ok, fail = upload_files(user, token, project_home)
        if fail > 0:
            print("有上传失败，继续尝试部署（可能不影响）")
        # 创建数据目录并放入初始 store（API 写文件会自动建目录）
        seed_path = "/api/v0/user/%s/files/path%s/data/store.json" % (user, project_home)
        initial = {"users": [], "products": [], "campaigns": [], "events": [], "orders": [],
                   "meta": {"seeded": False}}
        api(seed_path, token, "POST",
            multipart=("content", "store.json", json.dumps(initial).encode("utf-8")))
        print("  数据目录已准备")

        print("[2/4] 写入 WSGI 配置...")
        write_wsgi(user, token, domain)

        print("[3/4] 创建/配置 webapp...")
        code, res = api(base + "/webapps/", token)
        exists = False
        if code == 200 and isinstance(res, list):
            exists = any((w.get("domain_name") or "").lower() == domain.lower() for w in res)
        if not exists:
            code, res = api(base + "/webapps/", token, "POST",
                            {"domain_name": domain, "python_version": "python310"})
            print("  创建 webapp: HTTP %s" % code)
            if code not in (200, 201):
                print("  ", res)
        else:
            print("  webapp 已存在，跳过创建")

        # 配置 source_directory
        code, res = api(base + "/webapps/%s/" % domain, token, "PATCH",
                        {"source_directory": project_home})
        print("  设置 source_directory: HTTP %s" % code)
        if code not in (200, 201):
            print("  ", res)

        print("[4/4] 重载 webapp...")
        code, res = api(base + "/webapps/%s/reload/" % domain, token, "POST", {})
        print("  reload: HTTP %s %s" % (code, "" if code == 200 else res))

        print("\n=== 部署流程结束 ===")
        print("固定地址: https://%s" % domain)
        print("请等待 1-2 分钟后访问该地址验证。")

    elif step == "status":
        code, res = api(base + "/webapps/%s/" % domain, token)
        print("webapp HTTP", code, json.dumps(res, ensure_ascii=False, indent=2))
        code2, static = api(base + "/webapps/%s/static_files/" % domain, token)
        print("static HTTP", code2, json.dumps(static, ensure_ascii=False, indent=2))

    else:
        print("未知步骤:", step)


if __name__ == "__main__":
    main()
