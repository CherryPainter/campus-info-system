# ================= 校园宜知行 · 微信小程序前端（miniapp-frontend） =================

校园信息聚合与智能推送系统的微信小程序客户端。基于 **Taro 3.6 + React 18 + TypeScript + SCSS + NutUI React Taro + Zustand**，编译目标为微信小程序。

> 开发规范以《校园信息聚合与智能推送系统[前端].md》（仓库根）为准：
> 不虚构 API、不虚构数据字段、不擅自增加功能、严格按高保真原型实现 UI、后端业务逻辑零改动。

## 一、快速开始

```bash
# 1. 安装依赖（Node >= 18）
npm install

# 2. 启动编译（监听模式，产物在 dist/）
npm run dev:weapp

# 3. 用微信开发者工具打开本目录
#    - 导入项目：项目目录选 miniapp-frontend/
#    - AppID：project.config.json 已填入（wx5d3af9c6cc818db3）
#    - 本地设置 → 勾选「不校验合法域名」（开发期后端为 http://127.0.0.1:29528）
```

生产构建：`npm run build:weapp`（产物在 `dist/`，通过微信开发者工具「上传」发布）。

## 二、环境变量

配置统一写在 **单个 `miniapp-frontend/.env`**（已被 `.gitignore` 排除，不入库）：

| 变量 | 说明 |
| --- | --- |
| `TARO_APP_API_BASE` | 后端地址。本地联调 `http://127.0.0.1:29528`，生产 `https://yuetang.cloud` |
| `TARO_APP_DEV_TOKEN` | 开发期调试身份。**即使留空也必须保留这个 key**：`utils/storage.ts` 引用 `process.env.TARO_APP_DEV_TOKEN`，若 `.env` 缺该 key，Taro 的 DefinePlugin 不会内联，产物里会残留运行时 `process.env.X` → 小程序没有 `process` → **启动即崩（ReferenceError）**。空值＝不做任何假身份回退（未登录必须走真微信登录）；**绝不要把真实 dev token 写进线上包** |

> **为什么不用 `.env.development` / `.env.production`？** Taro 的 `taro build`（含 `--watch` 开发模式）其 `NODE_ENV` 恒为 `production`，**带后缀的 env 文件不会被加载** —— 写在那儿改了不生效，所以本项目统一用单个 `.env`。
>
> 另：命令行 `VAR=... npm run dev:weapp` 传入的同名变量会被 `.env` 里的值**覆盖**（dotenv `override`），要切后端请直接改 `.env` 后**重新编译**。
>
> 生产发布前需在小程序后台「开发管理-开发设置-服务器域名」配置 request 合法域名指向生产后端。

## 三、目录结构

```
miniapp-frontend/
├── config/                  # Taro 编译配置（index/dev/prod）
├── src/
│   ├── api/                 # API Service（唯一后端对接层，10 个文件）
│   │   ├── auth.ts          # 登录 / 刷新 / 登出
│   │   ├── user.ts          # 用户信息 / 学生资料 / 身份绑定
│   │   ├── schedule.ts      # 课表（today/week/current）
│   │   ├── weather.ts       # 天气（current/hourly/alerts）
│   │   ├── electricity.ts   # 电量（current/history）
│   │   ├── announcements.ts # 校园公告
│   │   ├── notification.ts  # 近期提醒（教学日历事件，v6.16.0 起对接真实接口）
│   │   ├── notifications.ts # 个人站内通知（消息中心）
│   │   ├── feedback.ts      # 意见反馈
│   │   └── webhook.ts       # 第三方消息通知（学生自建 webhook）
│   ├── components/          # 业务组件 18 个（WeatherCard / CourseCard / CourseDetail /
│   │                        #   ElectricityCard / ElectricityDailyDetail / NoticeCard /
│   │                        #   ReminderCard / TimelineItem / CampusCard / LoginModal /
│   │                        #   QuickAccess / UserInfoCard / FeedbackBadge / IconArrow /
│   │                        #   Switch / EmptyState / LoadingState / FeaturePlaceholder）
│   ├── pages/               # 30 个页面（以 app.config.ts 的 pages 数组为准）
│   │   ├── home/ schedule/ profile/          # 三个 TabBar 页
│   │   ├── coursetable/ coursedetail/ calendar/ classroom/ campus-card/
│   │   ├── electricity/ electricity-daily/ electricity-config/ weather/
│   │   ├── announcement/ favorites/ messages/ message-detail/
│   │   ├── feedback/(submit|list|detail) settings/ bind/ profile-detail/
│   │   ├── login/ third-party-notify/ third-party-sdks/ open-source/
│   │   └── user-agreement/ privacy-policy/ about/
│   ├── stores/
│   │   ├── authStore.ts                  # Token / 用户信息（zustand + persist）
│   │   ├── userStore.ts                  # 学生资料
│   │   └── notificationSettingsStore.ts  # 通知偏好
│   ├── styles/              # SCSS Design Token（variables / theme / common / iconfont）
│   ├── types/api.ts         # 前端 API 类型定义（以后端实际返回为准）
│   ├── utils/               # 10 个
│   │   ├── request.ts       # 统一请求层（401 自动刷新 + 错误归一）
│   │   ├── storage.ts       # Token 持久化
│   │   ├── auth.ts          # wx.login 封装
│   │   ├── bindGuard.ts     # 绑定引导期守卫（引导期禁发需绑定的私有接口）
│   │   ├── scheduleBigClass.ts  # 两节大课的展示拆分（仅前端）
│   │   ├── imagePreview.ts  # 图片点击放大统一封装
│   │   └── tabBarState.ts / weatherIcons.ts / feedbackBadge.ts / date.ts
│   ├── assets/              # images / tabbar（6 张 96×96 PNG）/ weather
│   ├── app.tsx              # 应用入口
│   └── app.config.ts        # 页面注册 / TabBar
├── types/                   # 全局类型声明（global.d.ts）
├── tools/                   # 辅助脚本（如 gen_weather_icons.py）
├── project.config.json      # 微信开发者工具项目配置
└── tsconfig.json
```

## 四、认证与请求

- 登录链路：`wx.login()` → `POST /api/miniapp/auth/login` → 后端换 openid 并签发 JWT 双 Token → 前端 `authStore` 持久化。
- 所有请求经 `utils/request.ts`：自动注入 `Authorization: Bearer`；遇 401 自动用 refreshToken 刷新并重放原请求（单飞锁防并发）。
- **刷新失败不跳登录页**：降级为游客态 + 只提示一次（合规要求：不自动弹登录、不强制跳转）。同理，命中 `403 STUDENT_NOT_BOUND` 也不跳转，只清身份缓存并抛错。
- Token 读写只允许在 `stores/authStore.ts`、`utils/storage.ts` 与 `utils/request.ts`，页面代码不直接操作。

## 五、TabBar

- `app.config.ts` 的 `tabBar.list` 为 **3 项**：`pages/home/index`（首页）、`pages/schedule/index`（Tab 文案「时间轴」）、`pages/profile/index`（我的）。
  > 注意**没有** `pages/timeline/` 目录 —— Tab 文案叫「时间轴」，而页面目录名是 `schedule`。
- 图标**已配置**：`src/assets/tabbar/` 下 6 张 **96×96 PNG**（home / timeline / profile 各「未选中 + 选中」两态），由 iconfont 字形渲染成 PNG —— 微信原生 tabBar 只接受图片文件，不支持字体图标。
- `custom: true` 启用**自定义 TabBar**：原生 tabBar 不支持单个 tab 的角标，故自绘（角标状态经 `utils/tabBarState.ts`）。

## 六、当前规模

> 本节原为「Phase 1–9 分阶段清单」，写于脚手架期（当时只完成到 Phase 3），已与实际严重脱节，故改为按代码事实陈述。功能与交互的权威描述见仓库根《校园信息聚合与智能推送系统[前端].md》与各页面实现；本文件只描述工程结构与构建方式，不重复功能清单。

- `app.config.ts` 注册 **30 个页面**（`src/pages/` 下 28 个目录），TabBar 3 项（首页 / 时间轴 / 我的）。
- API 层覆盖 10 个域：auth / user / schedule / weather / electricity / announcements / notification（近期提醒）/ notifications（站内通知）/ feedback / webhook（第三方消息通知）。
- 组件 18 个、utils 10 个、stores 3 个、styles 4 个（含 `iconfont.scss`）。
