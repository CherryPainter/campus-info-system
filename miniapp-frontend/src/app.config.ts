export default defineAppConfig({
  // 页面注册顺序：第一个为首页
  pages: [
    'pages/home/index',
    'pages/schedule/index',
    'pages/coursetable/index',
    'pages/coursedetail/index',
    'pages/profile/index',
    'pages/electricity/index',
    'pages/login/index',
    'pages/weather/index',
    'pages/announcement/detail/index',
    'pages/announcement/index/index',
    'pages/favorites/index',
    'pages/feedback/submit/index',
    'pages/feedback/list/index',
    'pages/feedback/detail/index',
    'pages/settings/index',
    'pages/profile-edit/index',
    'pages/electricity-config/index',
    'pages/messages/index',
    'pages/bind/index',
    'pages/profile-detail/index',
    'pages/user-agreement/index',
    'pages/privacy-policy/index',
  ],
  // 底部 TabBar：3 项（首页 / 时间轴 / 我的）
  // 图标由 iconfont 字体渲染成 PNG（96x96）：src/assets/tabbar/ 下
  // 微信 tabBar 图标只支持图片文件（不支持字体图标），所以走 PNG 路线
  // custom=true 启用自定义 TabBar（原生不支持单个 tab 角标，需自绘）
  tabBar: {
    custom: true,
    color: '#8a8f99',
    selectedColor: '#1a73e8',
    backgroundColor: '#ffffff',
    borderStyle: 'black',
    list: [
      {
        pagePath: 'pages/home/index',
        text: '首页',
        iconPath: 'assets/tabbar/home.png',
        selectedIconPath: 'assets/tabbar/home-active.png',
      },
      {
        pagePath: 'pages/schedule/index',
        text: '时间轴',
        iconPath: 'assets/tabbar/timeline.png',
        selectedIconPath: 'assets/tabbar/timeline-active.png',
      },
      {
        pagePath: 'pages/profile/index',
        text: '我的',
        iconPath: 'assets/tabbar/profile.png',
        selectedIconPath: 'assets/tabbar/profile-active.png',
      },
    ],
  },
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#f6f7fb',
    navigationBarTitleText: '校园宜知行',
    navigationBarTextStyle: 'black',
    backgroundColor: '#f6f7fb',
  },
});
