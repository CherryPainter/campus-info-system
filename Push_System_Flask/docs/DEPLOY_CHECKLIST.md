# Linux 部署检查报告与部署方案

> 检查日期：2026-06-25 | 项目版本：v6.11.2

---

## 一、端口与跨域检查结果

### 1.1 端口配置

| 检查项 | 当前值 | 位置 | 风险等级 | 部署建议 |
|--------|--------|------|----------|----------|
| Flask 监听端口 | `29528` | config.py:122 | 无风险 | 非标准端口，安全性好，保留 |
| Flask 绑定地址 | `0.0.0.0` | config.py:121, .env:8 | **高** | 改为 `127.0.0.1`（配合 Nginx 反向代理） |
| Nginx 监听端口 | `80` / `443` | DEPLOY_LINUX.md | 无风险 | 80 跳转 443，443 提供服务 |
| 前端开发端口 | `5173` | vite.config.ts:43 | 仅开发环境 | 生产环境不使用，Nginx 托管 dist/ |

**核心问题**：`HOST=0.0.0.0` 会导致 Flask 直接监听所有网络接口。如果防火墙未关闭 29528 端口，外部可直接访问 Flask 绕过 Nginx，跳过所有 Nginx 层安全防护。

### 1.2 CORS 跨域配置

| 检查项 | 当前值 | 位置 | 风险等级 | 说明 |
|--------|--------|------|----------|------|
| CORS 生效范围 | `r"/*"` 全局 | __init__.py:56 | 中 | 对所有路由生效，范围过大 |
| `supports_credentials` | `True` | __init__.py:56 | 中 | 允许携带 Cookie 跨域，前端 httpOnly cookie 依赖此项 |
| `.env` 中的 CORS_ORIGINS | 仅 localhost | .env:20 | **高** | 生产环境部署后前端域名不在白名单中，跨域请求会被拒绝 |
| `.env.linux` 中的 CORS_ORIGINS | `http://your-domain.com` 占位符 | .env.linux:24 | 中 | 需替换为实际域名 |
| 前端 `withCredentials` | `true` | request.ts:23 | 无风险 | 与后端 `supports_credentials=True` 对应 |
| 前端生产 baseURL | `/api`（相对路径） | request.ts:16 | 无风险 | 同源部署时不触发跨域 |

**关键结论**：如果使用 Nginx 反向代理（前端和 API 同域名），**不会产生跨域请求**，CORS 配置不影响功能。但 `.env` 中的 `CORS_ORIGINS` 仍需更新为生产域名，以防直接访问 API 端口时被拦截。

### 1.3 其他安全配置

| 检查项 | 当前值 | 风险等级 | 部署建议 |
|--------|--------|----------|----------|
| `DEBUG` | `false` | 无风险 | 保持关闭 |
| `FORCE_HTTPS` | `false`（.env 中有此变量） | 中 | 生产环境设为 `true`，或由 Nginx 处理 HTTPS |
| `AUTH_ENABLED` | `true` | 无风险 | 保持开启 |
| 数据库 | MySQL（仅支持） | 低 | 代码仅支持 MySQL，无 SQLite 回退；`DATABASE_TYPE` 非有效环境变量，无需设置；生产务必改强 `DATABASE_PASSWORD` |
| `DATABASE_PASSWORD` 默认值 | `123456` | **高** | config.py:267 的默认值，必须在 .env 中设置强密码 |
| `JWT_ADMIN_PASSWORD` | 空（回退到 ADMIN_TOKEN） | 中 | 建议在 .env 中显式设置管理员密码 |
| `SECRET_KEY` 自动生成 | 未设置时随机生成 | 中 | 每次重启变化导致 Token 失效，必须固定设置（v6.11.0 起：生产环境缺失即启动失败） |

---

## 二、生产环境 .env 配置模板

以下为 Linux 部署专用的 `.env` 配置，**复制为 `.env` 后修改标注项**：

```ini
# ========== 应用配置 ==========
APP_NAME=校园智能通知系统
APP_VERSION=6.11.2
DEBUG=false
HOST=127.0.0.1
PORT=29528

# ========== 安全配置 ==========
# [必改] 用 openssl rand -hex 32 生成
SECRET_KEY=<替换为你的64位十六进制密钥>
# [必改] 用 openssl rand -hex 16 生成
ADMIN_TOKEN=<替换为你的32位十六进制令牌>
AUTH_ENABLED=true
# 生产环境启用 HTTPS 强制跳转（如由 Nginx 处理 HTTPS 可设为 false）
FORCE_HTTPS=false

# ========== JWT 认证配置 ==========
JWT_ADMIN_USERNAME=admin
# [必改] 设置管理员登录密码（为空则使用 ADMIN_TOKEN）
JWT_ADMIN_PASSWORD=<设置一个强密码>
JWT_ACCESS_TOKEN_EXPIRE=3600
JWT_REFRESH_TOKEN_EXPIRE=604800

# ========== CORS 配置 ==========
# [必改] 替换为你的实际域名（多个用逗号分隔）
# 同域名部署（Nginx 反向代理）时此项不影响功能，但仍建议正确配置
CORS_ORIGINS=https://your-domain.com,http://localhost:5173

# ========== Python 路径 ==========
PYTHON_PATH=python3

# ========== 教务系统 ==========
JWXT_USERNAME=<你的学号>
JWXT_PASSWORD=<你的教务系统密码>
JWXT_HEADLESS=true
JWXT_TIMEOUT=180
JWXT_SAVE_LOG=true
JWXT_CAPTCHA_MODE=auto

# ========== 企业微信 ==========
WECOM_WEBHOOK=<你的企业微信机器人Webhook地址>
WECOM_STATUS_WEBHOOK=<你的状态告警Webhook地址>

# ========== 班级配置 ==========
CLASS_NAME=ZK2401

# ========== 定时任务 ==========
CRON_EXPRESSION=0 7,13 * * *

# ========== 推送规则 ==========
DAILY_PUSH_TIME=07:00
BEFORE_CLASS_MINUTES=15
BEFORE_END_CLASS_MINUTES=10

# ========== Tesseract OCR ==========
TESSERACT_CMD=/usr/bin/tesseract

# ========== 电量监控 ==========
ELECTRICITY_CRAWLER_COOKIE=<你的电表系统Cookie>
ELECTRICITY_CRAWLER_BASE_URL=http://dk.cqie.cn
ELECTRICITY_CRAWLER_MAX_PAGES=2
ELECTRICITY_LOW_POWER_THRESHOLD=10.0
ELECTRICITY_LOW_POWER_INTERVAL_HOURS=4.0
ELECTRICITY_SCHEDULE_DAILY=00:30
ELECTRICITY_SCHEDULE_WEEKLY=00:30
ELECTRICITY_SCHEDULE_WEEKLY_DAY=mon
ELECTRICITY_SCHEDULE_MONTHLY=00:30
ELECTRICITY_SCHEDULE_MONTHLY_DAY=1
ELECTRICITY_COOKIE_CHECK_TIME=20:00

# ========== 天气模块 ==========
QWEATHER_API_KEY=<你的和风天气API Key>
QWEATHER_LOCATION=101040100
QWEATHER_API_HOST=https://devapi.qweather.com
QWEATHER_LATITUDE=29.56
QWEATHER_LONGITUDE=106.55
QWEATHER_SCHEDULE_DAILY=07:00

# ========== 数据库（必填，仅支持 MySQL） ==========
# 取消注释并修改为你的 MySQL 配置
# DATABASE_HOST=localhost
# DATABASE_PORT=3306
# DATABASE_USER=push_system
# DATABASE_PASSWORD=你的强密码
# DATABASE_NAME=push_system
# DATABASE_PASSWORD=<强密码>
# DATABASE_NAME=push_system
```

---

## 三、Nginx 配置（生产环境）

以下为完整的 Nginx 配置文件，包含 HTTPS 和安全头：

```nginx
# /etc/nginx/sites-available/push-system

# HTTP -> HTTPS 跳转
server {
    listen 80;
    server_name your-domain.com;  # [必改] 替换为你的域名或 IP
    return 301 https://$server_name$request_uri;
}

# HTTPS 主服务
server {
    listen 443 ssl http2;
    server_name your-domain.com;  # [必改] 替换为你的域名或 IP

    # SSL 证书（用 certbot 自动配置，或手动指定）
    ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # 前端静态文件
    root /opt/Push_System_Flask/admin-frontend/dist;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;

        # 静态资源缓存
        location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
            expires 7d;
            add_header Cache-Control "public, immutable";
        }
    }

    # API 反向代理
    location /api/ {
        proxy_pass http://127.0.0.1:29528;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket 支持
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 超时设置
        proxy_connect_timeout 60s;
        proxy_read_timeout 120s;
        proxy_send_timeout 60s;
    }

    # 请求体大小限制
    client_max_body_size 10m;

    # 安全响应头
    add_header X-Frame-Options "DENY" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
```

---

## 四、systemd 服务配置

```ini
# /etc/systemd/system/push-system.service

[Unit]
Description=Campus Push System v6.11.2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/Push_System_Flask
Environment=PATH=/opt/Push_System_Flask/venv/bin:/usr/local/bin:/usr/bin
ExecStart=/opt/Push_System_Flask/venv/bin/python3 run.py
Restart=always
RestartSec=5
StandardOutput=append:/opt/Push_System_Flask/logs/service.out
StandardError=append:/opt/Push_System_Flask/logs/service.err

# 安全限制
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/opt/Push_System_Flask/data /opt/Push_System_Flask/logs /opt/Push_System_Flask/output

# 资源限制
LimitNOFILE=65535
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

---

## 五、完整部署步骤

### 5.1 上传项目

```bash
# 方式一：scp 上传（在本地执行）
scp -r Push_System_Flask/ root@your-server-ip:/opt/Push_System_Flask

# 方式二：rsync 上传（推荐，排除不需要的文件）
rsync -avz --exclude='venv' --exclude='node_modules' --exclude='.env' \
    Push_System_Flask/ root@your-server-ip:/opt/Push_System_Flask/
```

### 5.2 安装系统依赖

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3 python3-pip python3-venv python3-dev \
    tesseract-ocr tesseract-ocr-chi-sim \
    nginx \
    libgl1-mesa-glx libglib2.0-0 libnss3 libnspr4 \
    libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 \
    libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2
```

### 5.3 配置环境变量

```bash
cd /opt/Push_System_Flask

# 复制模板
cp .env.linux .env

# 生成安全密钥
echo "SECRET_KEY=$(openssl rand -hex 32)"
echo "ADMIN_TOKEN=$(openssl rand -hex 16)"

# 编辑配置
nano .env
# 按照上方模板修改所有标注 [必改] 的项
```

### 5.4 创建虚拟环境并安装依赖

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
playwright install-deps chromium
```

### 5.5 创建运行时目录

```bash
mkdir -p data/auth data/electricity/charts data/weather logs output
```

### 5.6 构建前端

```bash
cd /opt/Push_System_Flask/admin-frontend
npm install
npm run build
cd ..
```

### 5.7 设置权限

```bash
sudo chown -R www-data:www-data /opt/Push_System_Flask
sudo chmod -R 755 /opt/Push_System_Flask/data
sudo chmod -R 755 /opt/Push_System_Flask/logs
sudo chmod 600 /opt/Push_System_Flask/.env
```

### 5.8 配置 systemd 服务

```bash
sudo nano /etc/systemd/system/push-system.service
# 粘贴上方 systemd 配置

sudo systemctl daemon-reload
sudo systemctl enable push-system
sudo systemctl start push-system

# 验证
sudo systemctl status push-system
curl http://127.0.0.1:29528/api/ping
# 应返回 {"status":"ok"}
```

### 5.9 配置 Nginx

```bash
sudo nano /etc/nginx/sites-available/push-system
# 粘贴上方 Nginx 配置（替换 your-domain.com）

sudo ln -s /etc/nginx/sites-available/push-system /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### 5.10 配置 HTTPS（推荐）

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
sudo certbot renew --dry-run
```

### 5.11 配置防火墙

```bash
# 仅开放 80 和 443，不开放 29528
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw allow 22/tcp
sudo ufw enable

# 确认 29528 不对外暴露
sudo ufw status
```

### 5.12 设置时区

```bash
sudo timedatectl set-timezone Asia/Shanghai
```

---

## 六、部署验证清单

| 验证项 | 命令 | 预期结果 |
|--------|------|----------|
| Flask 服务运行 | `systemctl status push-system` | active (running) |
| 健康检查 | `curl http://127.0.0.1:29528/api/ping` | `{"status":"ok"}` |
| Nginx 配置 | `sudo nginx -t` | syntax is ok |
| 前端访问 | 浏览器打开 `https://your-domain.com` | 显示登录页 |
| API 代理 | 浏览器访问 `https://your-domain.com/api/ping` | `{"status":"ok"}` |
| 端口隔离 | `curl http://your-domain.com:29528/api/ping` | 连接超时（端口未开放） |
| HTTPS 跳转 | `curl -I http://your-domain.com` | 301 → https |
| Tesseract | `tesseract --version` | 4.x 或 5.x |
| 中文 OCR | `tesseract --list-langs \| grep chi_sim` | 显示 chi_sim |

---

## 七、常见问题

### Q1: 部署后前端登录提示"网络错误"或"跨域被拦截"

**原因**：`.env` 中 `CORS_ORIGINS` 未包含生产域名。

**解决**：如果使用 Nginx 同域名代理（前端和 API 都在 `https://your-domain.com` 下），不应出现跨域问题。检查 Nginx 的 `/api/` 反向代理是否正确配置。

如果前端和后端在不同域名，需在 `.env` 中添加前端域名：
```ini
CORS_ORIGINS=https://frontend-domain.com
```

### Q2: 登录后立即跳回登录页（Cookie 未携带）

**原因**：前端使用 httpOnly cookie 存储 JWT，需要同域名或正确配置 Cookie 的 SameSite 属性。

**解决**：使用 Nginx 同域名反向代理是最简单的方案。确保前端 `baseURL` 为 `/api`（相对路径），不要写成完整 URL。

### Q3: 课表爬虫启动失败

**原因**：Playwright Chromium 未安装或缺少系统依赖。

**解决**：
```bash
source venv/bin/activate
playwright install chromium
playwright install-deps chromium
```

### Q4: 管理员账号密码是什么

首次启动时，系统自动创建 `admin` 账号，密码为 `.env` 中 `JWT_ADMIN_PASSWORD` 的值。如果该项为空，则使用 `ADMIN_TOKEN` 的值。登录后可在管理后台修改密码。
