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

| 文件 | 变量 | 说明 |
| --- | --- | --- |
| `.env.development` | `TARO_APP_API_BASE` | 开发期后端地址，默认 `http://127.0.0.1:29528` |
| `.env.production` | `TARO_APP_API_BASE` | 生产后端，默认 `https://yuetang.cloud` |

> 生产发布前需在小程序后台「开发管理-开发设置-服务器域名」配置 request 合法域名指向生产后端。

## 三、目录结构

```
miniapp-frontend/
├── config/                  # Taro 编译配置（index/dev/prod）
├── src/
│   ├── api/                 # API Service（唯一后端对接层）
│   │   ├── auth.ts          # 登录 / 刷新 / 登出
│   │   ├── user.ts          # 用户信息 / 学生资料
│   │   ├── schedule.ts      # 课表（today/week/current）
│   │   ├── weather.ts       # 天气（current/hourly/alerts）
│   │   ├── electricity.ts   # 电量（current/history）
│   │   └── notification.ts  # 通知（占位：后端接口待实现，勿虚构）
│   ├── components/          # 业务组件（WeatherCard/CourseCard/... 后续 Phase 填充）
│   ├── pages/
│   │   ├── home/            # 首页（TabBar）
│   │   ├── timeline/        # 时间轴（TabBar）
│   │   ├── schedule/        # 课表（TabBar）
│   │   ├── notification/    # 通知（TabBar）
│   │   ├── profile/         # 我的（TabBar）
│   │   ├── login/           # 微信登录（未登录入口）
│   │   └── notification-detail/
│   ├── stores/
│   │   ├── authStore.ts     # Token / 用户信息（zustand + persist）
│   │   └── userStore.ts     # 学生资料
│   ├── styles/              # SCSS Design Token（variables/theme/common）
│   ├── types/api.ts         # 前端 API 类型定义（以后端实际返回为准）
│   ├── utils/
│   │   ├── request.ts       # 统一请求层（401 自动刷新 + 错误归一）
│   │   ├── storage.ts       # Token 持久化
│   │   ├── auth.ts          # wx.login 封装
│   │   └── date.ts          # 日期/问候语
│   ├── app.tsx              # 应用入口
│   └── app.config.ts        # 页面注册 / TabBar
├── project.config.json      # 微信开发者工具项目配置
└── tsconfig.json
```

## 四、认证与请求

- 登录链路：`wx.login()` → `POST /api/miniapp/auth/login` → 后端换 openid 并签发 JWT 双 Token → 前端 `authStore` 持久化。
- 所有请求经 `utils/request.ts`：自动注入 `Authorization: Bearer`；遇 401 自动用 refreshToken 刷新并重放原请求（单飞锁防并发）；刷新失败清空 Token 回登录页。
- Token 读写只允许在 `stores/authStore.ts` 与 `utils/request.ts`，页面代码不直接操作。

## 五、TabBar 图标（占位说明）

`app.config.ts` 的 tabBar 目前**仅文字**（未配 iconPath）。需要替换为设计稿图标时：

1. 在 `src/assets/tabbar/` 放置 6 张 **81×81 png**（home/timeline/schedule/notification/profile 各未选中 + 选中两态）；
2. 在 `app.config.ts` tabBar.list 对应项填入 `iconPath` / `selectedIconPath`。

## 六、开发阶段（按计划书 §29/§33）

- [x] Phase 1 项目初始化（Taro/React/TS/SCSS/NutUI/Zustand + 编译骨架）
- [x] Phase 2 基础设施（request / storage / authStore / API Service / 类型定义 / 错误处理）
- [x] Phase 3 微信登录（wx.login → 后端 → JWT 保存 → 自动鉴权；5 个 TabBar 页最小骨架）
- [ ] Phase 4 首页（问候/天气/今日课程/电量/通知）
- [ ] Phase 5 时间轴（课程+通知+电量时间线）
- [ ] Phase 6 课表（周切换/网格/详情）
- [ ] Phase 7 通知（列表/详情；**依赖后端 notification 接口**）
- [ ] Phase 8 我的（资料/设置/隐私/关于/退出登录）
- [ ] Phase 9 完整测试
