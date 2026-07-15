# Linux 部署指南

> 校园信息聚合与智能推送系统 v6.7.0 — Linux 生产环境完整部署文档

---

## 目录

- [系统要求](#系统要求)
- [快速开始](#快速开始)
- [详细部署步骤](#详细部署步骤)
- [systemd 服务配置](#systemd-服务配置)
- [Nginx 反向代理](#nginx-反向代理)
- [前端部署](#前端部署)
- [常见问题排查](#常见问题排查)
- [维护与更新](#维护与更新)

---

## 系统要求

| 项目 | 最低要求 | 推荐配置 |
|------|----------|----------|
| 操作系统 | Ubuntu 20.04 / Debian 11 / CentOS 8 | Ubuntu 22.04 LTS |
| Python | 3.10+ | 3.11+ |
| 内存 | 1GB | 2GB+ |
| 磁盘 | 5GB | 10GB+ |
| 网络 | 需访问和风天气 API、企业微信、教务系统 | — |

---

## 快速开始

```bash
# 1. 克隆项目
git clone <your-repo> Push_System_Flask
cd Push_System_Flask

# 2. 复制 Linux 配置模板
cp .env.linux .env
nano .env  # 编辑 .env 填写你的配置

# 3. 安装系统依赖
sudo apt update
sudo apt install -y python3 python3-pip python3-venv tesseract-ocr tesseract-ocr-chi-sim

# 4. 创建虚拟环境并安装依赖
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 5. 安装 Playwright（课表爬虫需要）
playwright install chromium
playwright install-deps chromium

# 6. 创建必要目录
mkdir -p data/auth data/electricity/charts data/weather logs output

# 7. 启动测试
python3 run.py
# 看到 "校园信息聚合与智能推送系统 v6.7.0 启动完成" 表示成功
```

---

## 详细部署步骤

### 1. 安装系统依赖

**Ubuntu/Debian：**

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-dev \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libpango-1.0-0 \
    libcairo2 \
    libasound2
```

> `libgl1-mesa-glx` 等图形库是 Playwright/Chromium 运行所需的系统依赖。

**CentOS/RHEL：**

```bash
sudo yum install -y \
    python3 \
    python3-pip \
    tesseract \
    tesseract-langpack-chi_sim
```

### 2. 创建项目目录

```bash
# 推荐部署到 /opt 目录
sudo mkdir -p /opt
sudo cp -r Push_System_Flask /opt/Push_System_Flask
cd /opt/Push_System_Flask
```

### 3. 配置环境变量

```bash
# 复制 Linux 配置模板
cp .env.linux .env
nano .env  # 或使用 vim .env
```

**必须修改的配置项：**

| 变量 | 说明 | 注意事项 |
|------|------|----------|
| `SECRET_KEY` | JWT 签名密钥 | 32 位以上随机字符串，用 `openssl rand -hex 32` 生成 |
| `ADMIN_TOKEN` | 管理令牌 | 16 位以上，也作为初始登录密码 |
| `JWXT_USERNAME` | 教务系统用户名 | 你的学号 |
| `JWXT_PASSWORD` | 教务系统密码 | 你的教务系统密码 |
| `WECOM_WEBHOOK` | 企业微信 Webhook | 机器人 Webhook URL |
| `QWEATHER_API_KEY` | 和风天气 API Key | 免费申请：https://dev.qweather.com/ |
| `ELECTRICITY_CRAWLER_COOKIE` | 电表系统 Cookie | 从浏览器 DevTools 获取 |

**生成安全密钥：**

```bash
# 生成 SECRET_KEY
openssl rand -hex 32
# 输出示例: a1b2c3d4e5f6...（64位十六进制字符串）

# 生成 ADMIN_TOKEN
openssl rand -hex 16
# 输出示例: f1e2d3c4b5a6...（32位十六进制字符串）
```

**Linux 专用配置（.env.linux 已预设）：**

```bash
# 使用 python3 而非 python
PYTHON_PATH=python3

# Tesseract 路径（Ubuntu 默认安装位置）
TESSERACT_CMD=/usr/bin/tesseract

# 生产环境关闭调试
DEBUG=false

# 监听所有网卡
HOST=0.0.0.0
```

### 4. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### 5. 安装 Playwright 浏览器

```bash
# 安装 Chromium 浏览器
playwright install chromium

# 安装 Chromium 所需的系统依赖
playwright install-deps chromium
```

> 如果服务器是无桌面环境（Server），Playwright 会自动使用 headless 模式。

### 6. 创建运行时目录

```bash
mkdir -p data/auth data/electricity/charts data/weather logs output
```

### 7. 验证 Tesseract 安装

```bash
tesseract --version
# 应显示 tesseract 4.x 或 5.x

# 测试中文识别支持
tesseract --list-langs | grep chi_sim
# 应显示 chi_sim
```

### 8. 测试运行

```bash
source venv/bin/activate
python3 run.py
```

看到以下日志表示启动成功：

```
校园信息聚合与智能推送系统 v6.7.0 启动完成
 * Running on http://0.0.0.0:29528
```

验证健康检查：

```bash
curl http://localhost:29528/api/health
# 应返回 {"status": "ok", ...}
```

---

## systemd 服务配置

### 创建服务文件

创建 `/etc/systemd/system/push-system.service`：

```ini
[Unit]
Description=Campus Push System v6.7.0
Documentation=https://github.com/your-repo/Push_System_Flask
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/Push_System_Flask
Environment=PATH=/opt/Push_System_Flask/venv/bin:/usr/local/bin:/usr/bin
EnvironmentFile=/opt/Push_System_Flask/.env
ExecStart=/opt/Push_System_Flask/venv/bin/python3 run.py
Restart=always
RestartSec=5
StandardOutput=append:/opt/Push_System_Flask/logs/service.out
StandardError=append:/opt/Push_System_Flask/logs/service.err

# 安全限制
NoNewPrivileges=true
PrivateTmp=true

# 资源限制
LimitNOFILE=65535
MemoryMax=512M

[Install]
WantedBy=multi-user.target
```

> **注意**：如果使用 `EnvironmentFile` 加载 `.env`，确保 `.env` 中不包含 `PATH` 等系统变量冲突项。也可以不使用 `EnvironmentFile`，让应用通过 `python-dotenv` 自动加载。

### 设置目录权限

```bash
# 设置项目目录所有者
sudo chown -R www-data:www-data /opt/Push_System_Flask

# 确保数据目录可写
chmod -R 755 /opt/Push_System_Flask/data
chmod -R 755 /opt/Push_System_Flask/logs
chmod -R 755 /opt/Push_System_Flask/output
```

### 启用和管理服务

```bash
# 重新加载 systemd 配置
sudo systemctl daemon-reload

# 启用开机自启
sudo systemctl enable push-system

# 启动服务
sudo systemctl start push-system

# 查看服务状态
sudo systemctl status push-system

# 查看实时日志
sudo journalctl -u push-system -f

# 停止服务
sudo systemctl stop push-system

# 重启服务
sudo systemctl restart push-system
```

### 日志管理

应用日志配置（`app/core/config.py`）：
- 日志文件：`logs/app.log`
- 单文件大小：10MB
- 保留备份数：5 个
- 总占用上限：约 50MB

```bash
# 查看应用日志
tail -f /opt/Push_System_Flask/logs/app.log

# 查看 systemd 标准输出
tail -f /opt/Push_System_Flask/logs/service.out

# 查看 systemd 错误日志
tail -f /opt/Push_System_Flask/logs/service.err
```

---

## Nginx 反向代理

### 安装 Nginx

```bash
sudo apt install -y nginx
```

### 配置文件

创建 `/etc/nginx/sites-available/push-system`：

```nginx
server {
    listen 80;
    server_name your-domain.com;  # 替换为你的域名或 IP

    # 前端静态文件
    location / {
        root /opt/Push_System_Flask/admin-frontend/dist;
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

        # WebSocket 支持（如需要）
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";

        # 超时设置
        proxy_connect_timeout 60s;
        proxy_read_timeout 120s;
        proxy_send_timeout 60s;
    }

    # 请求体大小限制（用于 Cookie 更新等接口）
    client_max_body_size 10m;

    # 安全头
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}
```

### 启用配置

```bash
# 创建软链接
sudo ln -s /etc/nginx/sites-available/push-system /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重载 Nginx
sudo systemctl reload nginx
```

### HTTPS 配置（推荐）

使用 Let's Encrypt 免费证书：

```bash
# 安装 certbot
sudo apt install -y certbot python3-certbot-nginx

# 获取证书并自动配置 Nginx
sudo certbot --nginx -d your-domain.com

# 自动续期（certbot 会自动添加 cron 任务）
sudo certbot renew --dry-run
```

---

## 前端部署

### 构建前端

```bash
# 进入前端目录
cd /opt/Push_System_Flask/admin-frontend

# 安装依赖
npm install

# 生产构建
npm run build
# 产出 dist/ 目录
```

### 构建后目录结构

```
admin-frontend/dist/
├── index.html
└── assets/
    ├── index-[hash].js
    ├── index-[hash].css
    └── ...
```

### 配置前端 API 地址

如果前端和后端不在同一域名下，需要修改 API 基础地址：

编辑 `admin-frontend/src/api/request.ts`，将 `baseURL` 改为后端实际地址：

```typescript
const request = axios.create({
    baseURL: 'https://your-domain.com/api',  // 修改为实际后端地址
    timeout: 15000,
});
```

然后重新构建：

```bash
npm run build
```

> 如果使用 Nginx 反向代理（如上方配置），前端和 API 在同一域名下，无需修改。

---

## 常见问题排查

### 1. Tesseract 找不到

```bash
# 检查是否安装
which tesseract

# 如果没有，安装：
sudo apt install -y tesseract-ocr tesseract-ocr-chi-sim

# 检查中文语言包
tesseract --list-langs | grep chi_sim

# 如果缺少中文包：
sudo apt install -y tesseract-ocr-chi-sim
```

### 2. Playwright 浏览器启动失败

```bash
# 安装系统依赖
playwright install-deps chromium

# 检查 Chromium 是否安装
playwright install chromium

# 如果服务器内存不足，可以设置环境变量减少内存使用
export CHROMIUM_FLAGS="--disable-dev-shm-usage --no-sandbox"
```

### 3. 权限问题

```bash
# 确保数据目录可写
sudo chown -R www-data:www-data /opt/Push_System_Flask/data
sudo chown -R www-data:www-data /opt/Push_System_Flask/logs
sudo chmod -R 755 /opt/Push_System_Flask/data
sudo chmod -R 755 /opt/Push_System_Flask/logs

# 确保 venv 可执行
sudo chmod +x /opt/Push_System_Flask/venv/bin/python3
```

### 4. 端口被占用

```bash
# 检查端口占用
sudo lsof -i :29528
# 或
sudo ss -tlnp | grep 29528

# 修改端口：编辑 .env 中的 PORT 变量
# PORT=29528
```

### 5. 时区问题

```bash
# 查看当前时区
timedatectl

# 设置上海时区
sudo timedatectl set-timezone Asia/Shanghai

# 验证
date
# 应显示 CST（中国标准时间）
```

### 6. 启动失败 — SECRET_KEY 或 ADMIN_TOKEN 未配置

```
错误信息：SECRET_KEY must be at least 32 characters
```

解决方法：

```bash
# 生成并写入 .env
echo "SECRET_KEY=$(openssl rand -hex 32)" >> .env
echo "ADMIN_TOKEN=$(openssl rand -hex 16)" >> .env
```

### 7. 和风天气 API 返回 401/403

- 检查 `QWEATHER_API_KEY` 是否正确
- 检查 API Key 是否已激活
- 免费版使用 `devapi.qweather.com`，付费版使用 `api.qweather.com`
- 检查 `QWEATHER_LOCATION` 是否为有效的 LocationID

### 8. 电量爬虫 Cookie 失效

- 重新从浏览器获取 Cookie（DevTools → Application → Cookies）
- 通过管理后台或 API 更新：`PUT /api/electricity/update_cookie`
- 检查 Cookie 有效期，系统会在每天 20:00 自动检测

### 9. 企业微信推送失败

- 检查 Webhook URL 是否正确
- 检查网络是否能访问 `qyapi.weixin.qq.com`
- 企业微信机器人每天最多推送 20 条消息（订阅消息限制）

---

## 维护与更新

### 更新代码

```bash
cd /opt/Push_System_Flask
git pull origin main

# 更新 Python 依赖
source venv/bin/activate
pip install -r requirements.txt

# 更新前端
cd admin-frontend
npm install
npm run build
cd ..

# 重启服务
sudo systemctl restart push-system
```

### 数据备份

建议定期备份以下目录：

```bash
# 备份运行时数据
tar -czf backup_$(date +%Y%m%d).tar.gz \
    data/auth/ \
    data/weather/ \
    data/electricity/ \
    .env

# 备份到远程（可选）
scp backup_$(date +%Y%m%d).tar.gz user@backup-server:/backups/
```

### 日志清理

日志自动轮转（10MB × 5 = 50MB 上限），通常无需手动清理。如需手动清理：

```bash
# 清理 30 天前的日志
find logs/ -name "*.log.*" -mtime +30 -delete
```

### 监控建议

- 使用 `systemctl status push-system` 检查服务状态
- 配置日志监控工具（如 logrotate 已由应用内置）
- 设置企业微信 `WECOM_STATUS_WEBHOOK` 接收系统状态通知

---

## 文件说明

| 文件/目录 | 说明 |
|-----------|------|
| `.env.linux` | Linux 环境配置模板 |
| `.env` | 实际配置文件（从 .env.linux 复制修改） |
| `.env.example` | 完整环境变量参考（47 个变量） |
| `requirements.txt` | Python 依赖（18 个包） |
| `run.py` | 应用入口 |
| `data/auth/` | JWT 密码哈希存储（自动生成） |
| `data/weather/` | 天气冷却状态（自动生成） |
| `data/electricity/` | 电量数据和图表（自动生成） |
| `logs/` | 应用日志（自动创建） |
| `admin-frontend/dist/` | 前端构建产物（npm run build 生成） |
