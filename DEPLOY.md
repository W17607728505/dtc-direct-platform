# DTC 平台长期部署指南

## 方案对比

| 方案 | 稳定性 | 固定域名 | 成本 | 适合场景 |
|---|---|---|---|---|
| A. Cloudflare 固定隧道（本地常驻） | 高 | 需自有域名 | 域名费 | 已有域名/Cloudflare 账号，数据留在本地 |
| B. Render / Fly.io（PaaS） | 高 | 平台免费域名 | 免费额度起 | 无服务器运维，最省事 |
| C. VPS + Docker Compose | 最高 | 需自有域名 | 服务器费 | 完全掌控，长期正式运营 |

> 当前临时隧道 `trycloudflare.com` 仅用于快速验证，地址会变，不适合长期推广。

---

## 方案 A：Cloudflare 固定隧道（推荐，成本最低）

前提：一个自有域名 + Cloudflare 免费账号（把域名 NS 接入 Cloudflare）。

1. 登录隧道（浏览器授权一次）：
   ```
   cloudflared tunnel login
   ```
2. 创建隧道：
   ```
   cloudflared tunnel create dtc-platform
   ```
   记下输出的 UUID。
3. 复制配置模板并填写：
   ```
   copy cloudflared-config.yml.example config.yml
   ```
   替换 `TUNNEL_UUID` 和 `DTC_DOMAIN`（如 `dtc.yourdomain.com`），
   `credentials-file` 改为生成的 JSON 实际路径。
4. 配置 DNS 路由：
   ```
   cloudflared tunnel route dns dtc-platform dtc.yourdomain.com
   ```
5. 启动本地服务（生产模式）：
   ```
   start_prod.bat
   ```
6. 启动隧道：
   ```
   cloudflared tunnel --config config.yml run
   ```
7. 设置 `DTC_BASE_URL=https://dtc.yourdomain.com` 后重启服务，
   使联邦 Actor / WebFinger 链接使用正式域名。

用 `cloudflared service install` 可把隧道注册为 Windows 服务，实现开机自启。

---

## 方案 B：Render 一键部署（当前选定方案，无需域名）

### 第 1 步：推送到 GitHub
1. 在 GitHub 网页创建一个**空仓库**（如 `dtc-platform`，不要勾选 README）。
2. 双击运行项目目录里的 `push_to_github.bat`。
3. 按提示输入 GitHub 用户名、仓库名、提交邮箱。
4. 脚本会自动完成首次提交并推送到 `main` 分支（不修改你的 git 全局配置）。
   - 若推送时弹出 GitHub 登录窗口，用浏览器/个人访问令牌（PAT）授权即可。

### 第 2 步：Render 创建服务
1. 打开 https://render.com → 用 GitHub 账号登录 → New → Web Service。
2. 选择刚推送的仓库 → Render 会自动识别 `render.yaml`（已配好启动命令和环境变量）。
3. 确认以下环境变量（render.yaml 已预置，可再核对）：
   - `HOST=0.0.0.0`、`PORT=8787`、`DTC_ENV=prod`、`DTC_ENABLE_RATE_LIMIT=1`
   - `DTC_BASE_URL` = 你的实际地址（见第 3 步）
   - `DTC_ADMIN_TOKEN` = 一个强随机字符串（保护管理接口）
4. 点击 Create Web Service，等待部署（首次约 2-5 分钟）。

### 第 3 步：确认正式地址（通常已预设，无需操作）
`render.yaml` 已预设 `DTC_BASE_URL=https://dtc-direct-platform.onrender.com`，与默认服务名一致，
部署后联邦 Actor / WebFinger 链接会自动使用这个地址，无需手动设置。

**唯一例外**：若 `dtc-direct-platform` 这个名字已被他人占用，Render 会提示改名或自动加后缀，
此时实际地址会不同（如 `https://dtc-direct-platform-xxxx.onrender.com`）。这种情况下到
Render 服务 → Environment → 把 `DTC_BASE_URL` 改成 Render 给出的实际地址，保存重启即可。

> 说明：前端分享链接用的是访问域名（`location.origin`），不受此项影响；`DTC_BASE_URL`
> 只用于联邦协议的 Actor / WebFinger 链接生成。

### 数据持久化说明（重要）
Render 免费方案**无持久磁盘**：实例重启或休眠后 `data/store.json` 会回到种子状态，
推广期间积累的分享、邀请、K 因子数据会丢失。应对方式：

- **短期快速验证**：接受重置即可，验证钩子效果不受影响。
- **需要保留数据**：用快照接口手动备份/恢复：
  ```
  REM 部署前备份当前数据
  curl https://你的地址/api/snapshot -o snapshot.json
  REM 重启后恢复
  curl -X POST https://你的地址/api/snapshot -H "Content-Type: application/json" -d @snapshot.json
  ```
  注意：带 `DTC_ADMIN_TOKEN` 时需加 `-H "X-Admin-Token: 你的令牌"`。
- **长期正式运营**：升级 Render 付费方案挂载持久磁盘，或改用方案 C / Fly.io（已配置持久化卷）。

免费方案另一个特性：15 分钟无访问会休眠，首次访问有约 30-50 秒冷启动。推广链接首次打开稍慢属正常。

注意：Render 免费方案无持久磁盘，重启后数据回到种子状态。挂载持久磁盘需付费方案。

---

## 方案 B2：Fly.io 部署（含持久化）

1. 安装 flyctl 并登录：`fly auth login`
2. 首次部署：`fly launch --no-deploy`
3. 创建持久卷：`fly volumes create dtc_data --region hkg --size 1`
4. 部署：`fly deploy`
5. 设置对外地址：`fly secrets set DTC_BASE_URL=https://dtc-direct-platform.fly.dev`

`fly.toml` 已配置健康检查与持久化挂载。

---

## 方案 C：VPS + Docker Compose

1. 上传项目到服务器，进入目录。
2. 设置环境变量：`export DTC_BASE_URL=https://your.domain`
3. 启动：`docker compose up -d`
4. 数据在命名卷 `dtc-data` 中持久化，重启不丢。
5. 用 Nginx/Caddy 反代并配置 HTTPS（或用 Cloudflare 隧道替代反代）。

---

## 生产环境检查清单

- [ ] `DTC_ENV=prod`（错误信息脱敏）
- [ ] `DTC_BASE_URL` 设为正式对外地址（影响联邦协议链接）
- [ ] `DTC_ENABLE_RATE_LIMIT=1`（防刷）
- [ ] `DTC_ADMIN_TOKEN` 设置强随机值（保护管理接口；公开传播接口自动放行）
- [ ] 数据目录 `DTC_DATA_DIR` 挂载持久化存储
- [ ] 健康检查 `GET /api/health` 返回 200
- [ ] HTTPS 已启用（PaaS/隧道通常自带）

## 验证命令

```
curl https://你的域名/api/health
```

返回 `{"status":"ok",...}` 即表示生产环境正常。
