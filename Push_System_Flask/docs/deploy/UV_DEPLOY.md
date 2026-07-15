# 用 uv 在 Linux 部署后端

> 本文以 **Linux（Ubuntu 20.04+ / Debian 11+）生产部署** 为例，使用 [uv](https://docs.astral.sh/uv/) 管理 Python 虚拟环境与依赖。
> uv 安装速度比 pip 快 10~100 倍，自带依赖解析与缓存。
> 后端语言栈：Flask 3.1 + SQLAlchemy 2.0 + Playwright + matplotlib + OpenCV 等。
> 前端（Node）与 uv 无关，保持原方式（`npm install && npm run build` 部署 `dist/`）。

---

## 0. 准备

1. 一台 Linux 服务器（建议 2C4G 起）。
2. 把项目传到服务器（二选一）：
   ```bash
   # 方式 A：git 克隆（如果仓库有 remote）
   git clone <你的仓库地址> /opt/push_system/Push_System_Flask
   cd /opt/push_system/Push_System_Flask

   # 方式 B：本地 scp 整个目录上去
   # scp -r D:\Tool\push_system\Push_System_Flask user@server:/opt/push_system/
   ```
3. 确认 `.env` 已就位（含 `SECRET_KEY` / `JWT_SECRET_KEY` / 数据库等配置）。

---

## 1. 安装 uv（Linux）

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env   # 让 uv 进入 PATH，或重开终端
uv --version
```

> 已装 pip 也可：`pip install uv`。

---

## 2. 系统级依赖（uv 管不了，需 apt 手动装）

```bash
sudo apt update
sudo apt install -y \
  tesseract-ocr \
  tesseract-ocr-chi-sim \     # 中文识别包，验证码含中文必须
  fonts-wqy-zenhei            # 图片中文渲染（文泉驿，TTF 格式，freetype 必能加载）
```

- `tesseract-ocr`：`pytesseract` 调用的引擎。
- `tesseract-ocr-chi-sim`：简体中文训练数据，识别中文验证码必需。
- `fonts-wqy-zenhei`：部署机缺中文字体会让图片里的中文变方框 □。
  **推荐用文泉驿而非 `fonts-noto-cjk`**：部分 Ubuntu 上 Noto CJK 以 `.ttc`
  集合字体形式提供，个别 freetype 版本加载时会报
  `FT2Font: Can not load face (unknown file format; error code 0x2)`，
  导致整个图表/课程图生成子进程崩溃（爬取被判失败）。
  文泉驿是标准 TTF，freetype 一定能加载，最为稳妥。
  若因字体缓存陈旧仍报错，可清缓存后重试：
  `rm -rf ~/.cache/matplotlib && sudo fc-cache -fv`。

---

## 3. 虚拟环境 + Python 依赖

```bash
cd /opt/push_system/Push_System_Flask

# 创建虚拟环境（默认 .venv）
uv venv

# 安装全部依赖（比 pip 快很多）
uv pip install -r requirements.txt
```

> ⚠️ `requirements.txt` 中 `requests==2.32.0` 被 PyPI 标记为 yanked（CVE-2024-35195 缓解冲突）。
> 建议升级到安全补丁版（无功能变更）：
> ```bash
> uv pip install "requests==2.32.4"
> ```

---

## 4. 安装 Playwright 浏览器内核（爬虫需要）

```bash
uv run playwright install --with-deps chromium
```

- `--with-deps` 会自动 `apt` 安装 Chromium 所需的系统库（libnss3、libatk-1.0、libgbm 等），省去手动排查。
- 浏览器内核约 150~300MB，首次需联网下载；国内可设镜像加速：
  ```bash
  export PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
  uv run playwright install --with-deps chromium
  ```

---

## 5. 运行后端

### 开发模式（前台调试，等价于原 `python run.py`）

```bash
uv run python run.py
```

读取 `.env` 的 `HOST=127.0.0.1`、`PORT=29528`、`DEBUG=false`。

### 生产模式（Gunicorn，推荐）

> ⚠️ `requirements.txt` **未包含 gunicorn**，需单独补装一次：

```bash
uv pip install gunicorn
uv run gunicorn -c gunicorn_config.py run:app
```

- 端口 `127.0.0.1:29528`，`preload_app=True`（调度器只在 master 启动一次，避免定时任务被多 worker 重复执行）。
- 生产环境用 Nginx 反代到该端口并启用 HTTPS（CSRF / Session Cookie 需 HTTPS）。

---

## 6. 生产化：systemd + Nginx（强烈建议）

### 6.1 systemd 服务

`/etc/systemd/system/push-system.service`：

```ini
[Unit]
Description=Campus Push System (uv)
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/opt/push_system/Push_System_Flask
# 直接调用 venv 里的 gunicorn，比 uv run 更稳（不依赖 shell 环境）
ExecStart=/opt/push_system/Push_System_Flask/.venv/bin/gunicorn -c gunicorn_config.py run:app
Restart=on-failure
RestartSec=5
# 关键：gunicorn_config.py 已设 preload_app=True，调度器只跑一次

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now push-system
sudo systemctl status push-system
```

> 也可继续用 `uv run gunicorn ...` 作为 ExecStart，但需 `Environment=PATH=.../.venv/bin:$PATH`，直接用 `.venv/bin/gunicorn` 最省事。

### 6.2 Nginx 反代（片段）

```nginx
server {
    listen 443 ssl;
    server_name your.domain;

    location / {
        proxy_pass http://127.0.0.1:29528;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

> 更完整的 Nginx / HTTPS / 静态资源（前端 dist）配置见 `DEPLOY_LINUX.md`。

---

## 7. 常见问题

| 现象 | 原因 | 解决 |
|---|---|---|
| `requests==2.32.0` yanked 警告 | PyPI 标记该版有 CVE 缓解冲突 | `uv pip install "requests==2.32.4"` |
| `tesseract is not installed` | 未装 Tesseract 或不在 PATH | `sudo apt install tesseract-ocr tesseract-ocr-chi-sim` |
| 图片中文变 □ | 缺中文字体 | `sudo apt install fonts-wqy-zenhei` |
| 图表/课程图生成崩溃 `Can not load face (unknown file format)` | 字体缓存指向损坏/不可加载字体文件（常见于 Noto CJK 的 `.ttc`） | 改用文泉驿 `fonts-wqy-zenhei`，并清缓存 `rm -rf ~/.cache/matplotlib && sudo fc-cache -fv`；代码已对不可加载字体做跳过+回退，正常情况下不会因此崩溃 |
| Playwright 浏览器下载慢/失败 | 网络限制 | 设 `PLAYWRIGHT_DOWNLOAD_HOST` 镜像后重试 |
| 验证码识别乱码 | 缺 `tesseract-ocr-chi-sim` | 安装简体中文数据包 |
| 端口 29528 被占用 | 旧进程残留 | `sudo lsof -i:29528` 查杀后重启 |
| 定时任务被执行多次 | worker 各自起调度器 | 确保 `gunicorn_config.py` 的 `preload_app=True` |

---

## 8. 日常命令速查

```bash
uv venv                                       # 建/重建虚拟环境
uv pip install -r requirements.txt            # 安装依赖
uv pip install <包>                           # 加装单个包
uv pip install "requests==2.32.4"             # 升级安全补丁
uv run python run.py                          # 开发启动
uv pip install gunicorn && \
uv run gunicorn -c gunicorn_config.py run:app # 生产启动
uv run playwright install --with-deps chromium# 装浏览器内核+系统库
sudo systemctl restart push-system            # 重启服务
```

---

## 附：进阶——改用 `uv sync` 现代工作流（可选）

把 `requirements.txt` 迁到 `pyproject.toml` 的 `[project.dependencies]`（含 `gunicorn`），
`uv lock` 生成 `uv.lock`，之后统一 `uv sync` 安装（自动建 venv + 装依赖 + 锁版本）。
本项目当前仍用 `requirements.txt`，按上面第 3~6 节即可。
