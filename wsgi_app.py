# -*- coding: utf-8 -*-
"""
WSGI 适配层：让 server.py 的全部业务逻辑运行在 PythonAnywhere 等 WSGI 主机上。
原理：复用 Handler 的路由与业务方法，仅把底层 socket 写入重定向到内存缓冲区。
原 HTTP Server 模式 (server.py) 不受影响，两种模式共存。
"""
import io
import os
import sys
from http.server import BaseHTTPRequestHandler

import server as srv


def _ensure_seeded():
    """WSGI 模式不会执行 server.main() 中的 seed，这里补齐：
    首次部署或 store 被清空后自动填充演示数据，避免接口因空数据报错。"""
    try:
        store = srv.load_store()
        if not store.get("meta", {}).get("seeded"):
            srv.seed(store, getattr(srv, "BASE_URL", None))
            srv.save_store(store)
    except Exception as e:
        sys.stderr.write("wsgi_app seed warning: %s\n" % e)


_ensure_seeded()


class _Buffer:
    """内存字节缓冲区，替代 socket 的 wfile"""
    def __init__(self):
        self._buf = io.BytesIO()

    def write(self, data):
        self._buf.write(data)
        return len(data)

    def getvalue(self):
        return self._buf.getvalue()


class WSGIHandler(srv.Handler):
    """继承全部业务方法，重写底层 IO 为内存缓冲"""

    def __init__(self, environ):
        # 跳过 BaseHTTPRequestHandler.__init__，直接初始化 WSGI 所需状态
        self.command = environ.get("REQUEST_METHOD", "GET")
        self.path = environ.get("PATH_INFO", "/") or "/"
        query = environ.get("QUERY_STRING", "")
        if query:
            self.path += "?" + query
        self.request_version = environ.get("SERVER_PROTOCOL", "HTTP/1.1")
        self.client_address = (environ.get("REMOTE_ADDR", "127.0.0.1"), 0)

        # 构造 headers 兼容对象（支持 .get）
        self.headers = {}
        for key, value in environ.items():
            if key.startswith("HTTP_"):
                hname = key[5:].replace("_", "-").title()
                self.headers[hname] = value
        if "CONTENT_TYPE" in environ:
            self.headers["Content-Type"] = environ["CONTENT_TYPE"]
        if "CONTENT_LENGTH" in environ:
            self.headers["Content-Length"] = environ["CONTENT_LENGTH"]

        # 请求体
        try:
            length = int(environ.get("CONTENT_LENGTH") or 0)
        except ValueError:
            length = 0
        raw = environ.get("wsgi.input").read(length) if length else b""
        self.rfile = io.BytesIO(raw)

        # 响应缓冲
        self.wfile = _Buffer()
        self._status = 200
        self._resp_headers = []

    # ---- 重写底层响应方法：存到内存而非 socket ----
    def send_response(self, code, message=None):
        self._status = code

    def send_header(self, keyword, value):
        self._resp_headers.append((keyword, value))

    def end_headers(self):
        pass

    def send_error(self, code, message=None, explain=None):
        self._status = code
        self._resp_headers.append(("Content-Type", "text/plain; charset=utf-8"))
        self.wfile.write(("%d %s" % (code, message or "Error")).encode("utf-8"))

    def log_message(self, fmt, *args):
        pass

    def result(self):
        status_text = {
            200: "OK", 201: "Created", 202: "Accepted", 204: "No Content",
            400: "Bad Request", 403: "Forbidden", 404: "Not Found",
            429: "Too Many Requests", 500: "Internal Server Error",
        }.get(self._status, "OK")
        return "%d %s" % (self._status, status_text), self._resp_headers, self.wfile.getvalue()


def application(environ, start_response):
    """WSGI 入口：PythonAnywhere 的 WSGI 配置文件指向此函数"""
    handler = WSGIHandler(environ)
    try:
        handler._handle(handler.command)
    except Exception as e:
        # 兜底：未捕获异常返回 JSON 错误
        handler._status = 500
        handler._resp_headers = [("Content-Type", "application/json; charset=utf-8")]
        handler.wfile = _Buffer()
        handler.wfile.write(
            ("{\"error\":\"server error\",\"detail\":\"%s\"}" % str(e)).encode("utf-8")
        )
    status, headers, body = handler.result()
    start_response(status, headers)
    return [body]
