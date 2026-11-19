# -*- coding: utf-8 -*-
"""生产化配置：全部通过环境变量注入，适配 PaaS / 容器 / 本地部署"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 数据目录：默认项目内 data；PaaS 可挂载持久化卷到该路径（如 /data）
DATA_DIR = os.environ.get("DTC_DATA_DIR", os.path.join(BASE_DIR, "data"))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
STORE_PATH = os.path.join(DATA_DIR, "store.json")

# 监听：容器内必须 0.0.0.0；本地默认 127.0.0.1
HOST = os.environ.get("HOST", "127.0.0.1")
PORT = int(os.environ.get("PORT", "8787"))

# 对外访问地址（用于协议端点生成 Actor/WebFinger 链接）
BASE_URL = os.environ.get("DTC_BASE_URL", "http://%s:%d" % (
    "127.0.0.1" if HOST in ("127.0.0.1", "localhost") else HOST, PORT))

# 访问控制
ADMIN_TOKEN = os.environ.get("DTC_ADMIN_TOKEN", "")          # 置空则不开启写操作保护
RATE_LIMIT_PER_MIN = int(os.environ.get("DTC_RATE_LIMIT", "120"))  # 单 IP 每分钟请求上限
ENABLE_RATE_LIMIT = os.environ.get("DTC_ENABLE_RATE_LIMIT", "0") == "1"

# 运行环境
ENV = os.environ.get("DTC_ENV", "dev")  # dev / prod
DEBUG = ENV != "prod"
