import { useState, useRef, useEffect } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, { useLoad, useDidShow } from '@tarojs/taro';

import * as electricityApi from '@/api/electricity';
import * as userApi from '@/api/user';
import * as notificationsApi from '@/api/notifications';
import type { ElectricityCurrent } from '@/types/api';
import dayjs from 'dayjs';
import { logout as logoutApi } from '@/api/auth';
import { useAuthStore } from '@/stores/authStore';
import { useUserStore } from '@/stores/userStore';
import { setTabIndex } from '@/utils/tabBarState';
import CampusCard from '@/components/CampusCard';
import FeedbackBadge from '@/components/FeedbackBadge';
import LoginModal from '@/components/LoginModal';
import { useFeedbackBadge } from '@/hooks/useFeedbackBadge';
import { useLoginGuard } from '@/hooks/useLoginGuard';
import { useBindStatusWatcher } from '@/hooks/useBindStatusWatcher';
import { isBindGuideActive } from '@/utils/bindGuard';
import './index.scss';

/**
 * 我的页（按原型图重做）
 * 结构（自上而下）：
 * - 顶部资料头部（大头像 + 姓名 + 专业年级 + 右上二维码/消息）
 * - 校园卡（蓝卡，展示校园卡号，占位：后端无接口）
 * - 宿舍用电（剩余 + 本月已用，两列）
 * - 功能列表（我的消息/我的课表/收藏/反馈/设置/退出登录）
 */
export default function ProfilePage() {
  const { user, refreshToken, logout: clearAuth, isLoggedIn } = useAuthStore();
  const { profile, setProfile } = useUserStore();
  // 登录守卫：游客态点击受限功能时弹 LoginModal
  const { guard, modalProps } = useLoginGuard();
  // 身份状态主动监察：管理员解绑后清空身份缓存并跳绑定页（承接「解绑/收回身份」）
  useBindStatusWatcher();
  // 反馈未读红点（已受理未查看的反馈数）
  const { count: feedbackUnread, refresh: refreshFeedbackBadge } = useFeedbackBadge();
  // 消息未读（站内通知 + 新公告，消息图标角标）
  const [msgUnread, setMsgUnread] = useState(0);

  const [statusBarHeight, setStatusBarHeight] = useState(20);
  const [electricity, setElectricity] = useState<ElectricityCurrent | null>(null);
  // 是否已配置电表 Cookie（false = 未配置，宿舍用电卡片引导去设置；null = 未知）
  const [cookieConfigured, setCookieConfigured] = useState<boolean | null>(null);
  const [monthUsed, setMonthUsed] = useState<number | null>(null);
  const [updateTime, setUpdateTime] = useState<string | null>(null);
  // 楼栋信息：取自电量接口的 meter 字段（真实库值为"电表: 31栋512照明"），清洗后展示
  const [roomText, setRoomText] = useState<string | null>(null);

  // 清洗电表名：去掉"电表:"前缀与"照明"后缀 → "31栋512"
  const cleanMeter = (meter?: string): string => {
    if (!meter) return '';
    return meter
      .replace(/^电表[:：]\s*/, '')
      .replace(/照明$/, '')
      .trim();
  };

  const loadAll = async () => {
    // 并行：电量当前值 + 本月累计（后端聚合）+ 资料（无缓存时拉取）
    // 说明：本月已用改由后端 /electricity/monthly 按自然月 SUM 返回，
    // 不再前端拉取 1000 条记录本地累加（此前与详情页取数条数不同导致两处数值不一致）
    const [eRes, hRes, pRes] = await Promise.all([
      electricityApi
        .getCurrent()
        .then((r) => ({
          ok: true as const,
          d: r.data.electricity,
          configured: r.data.cookie_configured ?? null,
        }))
        .catch(() => ({ ok: false as const, d: null, configured: null })),
      electricityApi
        .getMonthlyUsage()
        .then((r) => ({ ok: true as const, d: { sum: r.data.month_used ?? 0 } }))
        .catch(() => ({ ok: false as const, d: { sum: 0 } })),
      // 始终拉取最新资料（不再用 !profile 缓存短路）：既让昵称/真名等编辑即时生效，
      // 也让管理员解绑后本接口返回 403 触发跳绑定页、本地缓存被清空
      userApi
        .getProfile()
        .then((r) => ({ ok: true as const, d: r.profile }))
        .catch(() => ({ ok: false as const, d: null })),
    ]);

    setElectricity(eRes.ok ? eRes.d : null);
    if (eRes.configured != null) setCookieConfigured(eRes.configured);
    setMonthUsed(hRes.ok ? hRes.d.sum : 0);
    // 更新时间统一显示"访问这一刻"（本次请求已确认数据真实性），覆盖后端爬取时间戳
    if (eRes.ok && eRes.d) setUpdateTime(dayjs().format('YYYY-MM-DD HH:mm:ss'));
    // 楼栋信息：取自电量接口的 meter（后端 get_building_meter 已从用电记录解析出可读楼栋，
    // 形如"31栋512照明"），清洗后展示；拿不到时回退班级名
    if (eRes.ok && eRes.d?.meter) {
      const cleaned = cleanMeter(eRes.d.meter);
      if (cleaned) setRoomText(cleaned);
    }
    if (pRes.ok && pRes.d) setProfile(pRes.d);
  };

  // 消息未读统计（站内通知 + 新公告），失败静默不影响主体
  const loadMsgUnread = async () => {
    try {
      const res = await notificationsApi.getUnreadCount();
      setMsgUnread(res?.data?.total ?? 0);
    } catch {
      /* 静默失败 */
    }
  };

  useLoad(() => {
    // custom 导航栏：读取状态栏高度，避免内容被遮挡
    try {
      const info = Taro.getWindowInfo();
      if (info.statusBarHeight) setStatusBarHeight(info.statusBarHeight);
    } catch {
      // 兜底 20
    }
    // 游客态：保留完整 UI（"先体验后授权"），仅数据用占位、点击用 LoginModal 引导登录
    refreshPrivate();
  });

  // 电量轻量刷新（后台触发，成功后更新展示值；更新时间显示"访问这一刻"）
  const refreshElectricity = () => {
    electricityApi.refresh().then((r) => {
      // 刷新返回的 cookie_configured 与 current 一致，一并同步（未配置时为 false）
      if (r?.data?.cookie_configured != null) {
        setCookieConfigured(r.data.cookie_configured);
      }
      const e = r?.data?.electricity;
      if (e) {
        setElectricity(e);
        // 用客户端当前时间作为更新时间（本次请求已确认数据真实性），而非后端爬取时间戳
        setUpdateTime(dayjs().format('YYYY-MM-DD HH:mm:ss'));
      }
    }).catch(() => { /* 刷新失败保留缓存 */ });
  };

  // 一次性拉取"我的"页全部需登录/绑定的数据。
  // 引导期（登录成功未绑定、正被引导去绑定页）内不发任何私有请求：
  // 未绑定阶段这些接口必然 403，发了纯浪费 + 刷 403 噪音（此前用 isLoggedIn 判定，
  // 但登录成功未绑定 isLoggedIn 已为 true，仍会误发，根因同绑定引导护栏）。
  const refreshPrivate = () => {
    if (!isLoggedIn || isBindGuideActive()) return;
    loadAll();
    refreshElectricity();
    refreshFeedbackBadge();
    loadMsgUnread();
  };

  // "我的"是 TabBar 第 2 项：每次显示广播自身下标，保证 TabBar 选中态与任意进入路径一致
  useDidShow(() => {
    setTabIndex(2);
  });

  // "我的"是 TabBar 页：切 Tab 离开再回来时页面常驻内存，非首次 onShow 也刷新一次
  const firstShowRef = useRef(true);
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false;
      return; // 首次进入走 useLoad，不重复
    }
    refreshPrivate();
  });

  // 登录态变化（游客 → 已登录，如从登录页返回）：补齐需登录的数据加载
  useEffect(() => {
    refreshPrivate();
    // 游客态 / 绑定引导期不发私有请求，故不依赖 isLoggedIn 单值（refreshPrivate 内部判定）
  }, [isLoggedIn]);

  const handleLogout = () => {
    Taro.showModal({
      title: '退出登录',
      content: '确定要退出当前账号吗？',
      confirmText: '退出',
      confirmColor: '#e8380f',
      success: async (res) => {
        if (!res.confirm) return;
        try {
          await logoutApi(refreshToken || undefined);
        } catch {
          // 后端登出失败不阻塞本地退出
        }
        // 仅清空本地登录态，留在「我的」页自动渲染游客态（引导卡 + 登录入口），
        // 不要 reLaunch 到登录页 —— 那样等于"退出即强登录"，违反"先体验后授权"合规
        clearAuth();
      },
    });
  };

  // 展示名：已登录用「昵称/真名/用户名/同学」；游客态显示「登录」（点击直达登录页）
  const name = isLoggedIn
    ? profile?.nickname || profile?.real_name || user?.username || '同学'
    : '登录';
  const majorGrade = isLoggedIn
    ? [profile?.major, profile?.grade ? `${profile.grade}级` : '']
        .filter(Boolean)
        .join(' · ')
    : '登录后查看个人资料与数据';

  return (
    <View className="page profile-page">
      {/* 顶部 hero 区：承载头像/姓名/操作，自带默认径向渐变背景。
         顶部 paddingTop = statusBarHeight(避状态栏) + 80rpx(避系统胶囊)，
         让 hero 从 page 顶部就开始铺，渐变覆盖到状态栏下方的"间距区"避免纯白留白 */}
      <View
        className="profile-hero"
        style={{ paddingTop: `calc(${statusBarHeight}px + 80rpx)` }}
      >
        <View className="profile-header">
          {/* 左侧：头像 + 昵称
              合规与体验：游客点头像**直接进登录页**，不再经过"登录弹窗"这层中间层；
              已登录跳个人资料详情页。 */}
          <View
            className="profile-header-info"
            onClick={() =>
              isLoggedIn
                ? Taro.navigateTo({ url: '/pages/profile-detail/index' })
                : Taro.navigateTo({ url: '/pages/login/index' })
            }
          >
            {isLoggedIn && user?.avatar ? (
              <Image src={user.avatar} className="profile-avatar" mode="aspectFill" />
            ) : (
              <View className="profile-avatar profile-avatar-placeholder">
                <Text className="profile-avatar-text">
                  {isLoggedIn ? name.slice(0, 1) : '登'}
                </Text>
              </View>
            )}
            <View className="profile-info">
              <Text className="profile-name">{name}</Text>
              <Text className="profile-sub">{majorGrade}</Text>
            </View>
          </View>
          <View className="profile-header-actions">
            {/* 二维码（保留在上方）：占位功能，未登录不需特殊处理 */}
            <View
              className="profile-qr"
              onClick={() => Taro.showToast({ title: '等待学校开放接口', icon: 'none' })}
            >
              <Text className="iconfont icon-erweima profile-qr-icon" />
            </View>
            {/* 消息入口：游客态点击 → 登录引导；已登录跳消息页 + 未读角标 */}
            <View
              className="profile-msg"
              onClick={() =>
                guard(() => Taro.navigateTo({ url: '/pages/messages/index' }))
              }
            >
              <Text className="iconfont icon-tongzhi profile-msg-icon" />
              {isLoggedIn && msgUnread > 0 && (
                <View className="profile-msg-badge">
                  <Text className="profile-msg-badge-num">
                    {msgUnread > 99 ? '99+' : msgUnread}
                  </Text>
                </View>
              )}
            </View>
          </View>
        </View>

        {/* 校园卡（蓝卡，展示校园卡号；占位：后端无校园卡数据接口，卡面不含余额金额/充值，规避审核金融观感），放在 hero 区让自定义背景渐变铺到卡下沿 */}
        <CampusCard cardNumber={isLoggedIn ? profile?.campus_card_number : undefined} />
      </View>

      {/* 宿舍用电：游客态数值显示 --、底部按钮文案「去登录」 */}
      <View className="card dorm-card">
        <View className="dorm-header">
          <Text className="card-title">
            宿舍用电
            {isLoggedIn && (roomText || profile?.class_name)
              ? `（${roomText || profile?.class_name}）`
              : ''}
          </Text>
          <Text
            className="card-more"
            onClick={() =>
              guard(() => Taro.navigateTo({ url: '/pages/electricity/index' }))
            }
          >
            更多 ›
          </Text>
        </View>
        <View className="dorm-stats">
          <View className="dorm-stat">
            <Text className="dorm-stat-label">剩余电量（度）</Text>
            <Text className="dorm-stat-value dorm-stat-value-remaining">
              {isLoggedIn && electricity?.remaining != null
                ? electricity.remaining.toFixed(2)
                : '--'}
            </Text>
          </View>
          <View className="dorm-stat-divider" />
          <View className="dorm-stat">
            <Text className="dorm-stat-label">本月已用（度）</Text>
            <Text className="dorm-stat-value dorm-stat-value-used">
              {isLoggedIn && monthUsed != null ? monthUsed.toFixed(2) : '--'}
            </Text>
          </View>
        </View>
        <View className="dorm-foot">
          {!isLoggedIn ? (
            <>
              <Text className="dorm-foot-time">登录后查看宿舍用电</Text>
              {/* 按钮文案即"去登录"：直接进登录页，不再套一层弹窗 */}
              <View
                className="dorm-foot-btn"
                onClick={() => Taro.navigateTo({ url: '/pages/login/index' })}
              >
                <Text>去登录</Text>
              </View>
            </>
          ) : cookieConfigured === false ? (
            <>
              <Text className="dorm-foot-time">未配置电表接入信息</Text>
              <View
                className="dorm-foot-btn"
                onClick={() => Taro.navigateTo({ url: '/pages/electricity-config/index' })}
              >
                <Text>去设置</Text>
              </View>
            </>
          ) : (
            <>
              <Text className="dorm-foot-time">
                {updateTime ? `更新时间：${updateTime}` : '暂无更新'}
              </Text>
              <View
                className="dorm-foot-btn"
                onClick={() => Taro.navigateTo({ url: '/pages/electricity/index' })}
              >
                <Text>用电详情</Text>
              </View>
            </>
          )}
        </View>
      </View>

      {/* 功能列表：游客态全部点击 → 登录引导；已登录保持原行为 */}
      <View className="card profile-list">
        {/* 我的消息：消息图标 + 未读角标（与顶部图标双入口，避免找不到） */}
        <View
          className="profile-item"
          onClick={() =>
            guard(() => Taro.navigateTo({ url: '/pages/messages/index' }))
          }
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-tongzhi profile-item-icon" />
          </View>
          <Text className="profile-label">我的消息</Text>
          {isLoggedIn ? <FeedbackBadge count={msgUnread} /> : null}
          <Text className="profile-arrow">›</Text>
        </View>
        {/* 我的课表：跳到课表详情页（周视图，含周次切换/课程卡片），而不是首页 tabBar 的「时间轴」 */}
        <View
          className="profile-item"
          onClick={() =>
            guard(() => Taro.navigateTo({ url: '/pages/coursetable/index' }))
          }
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-kechengbiao profile-item-icon" />
          </View>
          <Text className="profile-label">我的课表</Text>
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() =>
            guard(() => Taro.navigateTo({ url: '/pages/favorites/index' }))
          }
        >
          <View className="profile-item-icon-wrap">
            <Text className="profile-item-icon profile-star-icon">{'\u2606'}</Text>
          </View>
          <Text className="profile-label">我的收藏</Text>
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() =>
            guard(() => Taro.navigateTo({ url: '/pages/feedback/submit/index' }))
          }
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-yijianyufankui profile-item-icon" />
          </View>
          <Text className="profile-label">意见反馈</Text>
          {isLoggedIn ? <FeedbackBadge count={feedbackUnread} /> : null}
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() =>
            guard(() => Taro.navigateTo({ url: '/pages/settings/index' }))
          }
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-shezhi profile-item-icon" />
          </View>
          <Text className="profile-label">设置</Text>
          <Text className="profile-arrow">›</Text>
        </View>
      </View>

      {/* 退出登录：仅已登录显示 */}
      {isLoggedIn ? (
        <View className="logout-btn" onClick={handleLogout}>
          <Text className="logout-text">退出登录</Text>
        </View>
      ) : null}

      {/* 登录引导弹窗：游客态点击受限功能时弹出（useLoginGuard 管理显隐） */}
      <LoginModal {...modalProps} />
    </View>
  );
}