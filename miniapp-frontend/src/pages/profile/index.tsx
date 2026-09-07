import { useState, useRef } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, { useLoad, useDidShow } from '@tarojs/taro';

import * as electricityApi from '@/api/electricity';
import * as userApi from '@/api/user';
import * as notificationsApi from '@/api/notifications';
import type { ElectricityCurrent, ElectricityRecord } from '@/types/api';
import dayjs from 'dayjs';
import { logout as logoutApi } from '@/api/auth';
import { useAuthStore } from '@/stores/authStore';
import { useUserStore } from '@/stores/userStore';
import { setTabIndex } from '@/utils/tabBarState';
import CampusCard from '@/components/CampusCard';
import FeedbackBadge from '@/components/FeedbackBadge';
import { useFeedbackBadge } from '@/hooks/useFeedbackBadge';
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
  const { user, refreshToken, logout: clearAuth } = useAuthStore();
  const { profile, setProfile } = useUserStore();
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
    // 并行：电量当前值 + 用电历史（本月聚合）+ 资料（无缓存时拉取）
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
        .getHistory(1000)
        .then((r) => {
          const records = r.data.records as ElectricityRecord[];
          // 本月（按 record_time 北京时间字符串判断），累加 usage
          const monthStart = dayjs().startOf('month');
          const sum = records.reduce((acc, rec) => {
            const t = rec.record_time || rec.time;
            if (!t) return acc;
            const d = dayjs(t);
            if (d.isValid() && (d.isAfter(monthStart) || d.isSame(monthStart))) {
              return acc + Number(rec.usage || 0);
            }
            return acc;
          }, 0);
          // 取第一条 record 的 meter 作为楼栋号来源
          // （electricity_remaining.meter 是 'default'，真实楼栋号在 electricity_records.meter）
          const meter = records.length > 0 ? records[0].meter : '';
          return { ok: true as const, d: { sum, meter } };
        })
        .catch(() => ({ ok: false as const, d: { sum: 0, meter: '' } })),
      !profile
        ? userApi
            .getProfile()
            .then((r) => ({ ok: true as const, d: r.profile }))
            .catch(() => ({ ok: false as const, d: null }))
        : Promise.resolve({ ok: true as const, d: profile }),
    ]);

    setElectricity(eRes.ok ? eRes.d : null);
    if (eRes.configured != null) setCookieConfigured(eRes.configured);
    setMonthUsed(hRes.ok ? hRes.d.sum : 0);
    // 更新时间统一显示"访问这一刻"（本次请求已确认数据真实性），覆盖后端爬取时间戳
    if (eRes.ok && eRes.d) setUpdateTime(dayjs().format('YYYY-MM-DD HH:mm:ss'));
    // 楼栋信息：取自 electricity_records.meter（hRes.d.meter），回退 class_name
    if (hRes.ok && hRes.d.meter) {
      const cleaned = cleanMeter(hRes.d.meter);
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
    loadAll();
    // 打开"我的"页即触发一次电量轻量刷新（后端 60s 冷却），完成后更新最新值
    refreshElectricity();
    // 反馈未读红点
    refreshFeedbackBadge();
    // 消息未读角标
    loadMsgUnread();
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
    loadAll();
    refreshElectricity();
    // 从反馈详情返回后刷新红点（查看一条即 -1）
    refreshFeedbackBadge();
    // 从消息页返回后刷新未读角标（已读会减数）
    loadMsgUnread();
  });

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
        clearAuth();
        Taro.reLaunch({ url: '/pages/login/index' });
      },
    });
  };

  // 展示名优先级：昵称 → 真实姓名 → 用户名 → 兜底
  const name = profile?.nickname || profile?.real_name || user?.username || '同学';
  const majorGrade = [profile?.major, profile?.grade ? `${profile.grade}级` : '']
    .filter(Boolean)
    .join(' · ');

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
          {/* 左侧：头像 + 昵称（可点跳详情页）；右侧：二维码 + 消息 */}
          <View
            className="profile-header-info"
            onClick={() => Taro.navigateTo({ url: '/pages/profile-detail/index' })}
          >
            {user?.avatar ? (
              <Image src={user.avatar} className="profile-avatar" mode="aspectFill" />
            ) : (
              <View className="profile-avatar profile-avatar-placeholder">
                <Text className="profile-avatar-text">{name.slice(0, 1)}</Text>
              </View>
            )}
            <View className="profile-info">
              <Text className="profile-name">{name}</Text>
              {majorGrade ? <Text className="profile-sub">{majorGrade}</Text> : null}
            </View>
          </View>
          <View className="profile-header-actions">
            {/* 二维码（保留在上方） */}
            <View
              className="profile-qr"
              onClick={() => Taro.showToast({ title: '等待学校开放接口', icon: 'none' })}
            >
              <Text className="iconfont icon-erweima profile-qr-icon" />
            </View>
            {/* 消息入口（替换原「更多」图标位置）：点击进「我的消息」，右上角红点显示未读数 */}
            <View
              className="profile-msg"
              onClick={() => Taro.navigateTo({ url: '/pages/messages/index' })}
            >
              <Text className="iconfont icon-tongzhi profile-msg-icon" />
              {msgUnread > 0 && (
                <View className="profile-msg-badge">
                  <Text className="profile-msg-badge-num">{msgUnread > 99 ? '99+' : msgUnread}</Text>
                </View>
              )}
            </View>
          </View>
        </View>

        {/* 校园卡（蓝卡，展示校园卡号；占位：后端无校园卡数据接口，卡面不含余额金额/充值，规避审核金融观感），放在 hero 区让自定义背景渐变铺到卡下沿 */}
        <CampusCard cardNumber={profile?.campus_card_number} />
      </View>

      {/* 宿舍用电 */}
      <View className="card dorm-card">
        <View className="dorm-header">
          <Text className="card-title">
            宿舍用电{roomText || profile?.class_name ? `（${roomText || profile?.class_name}）` : ''}
          </Text>
          <Text
            className="card-more"
            onClick={() => Taro.navigateTo({ url: '/pages/electricity/index' })}
          >
            更多 ›
          </Text>
        </View>
        <View className="dorm-stats">
          <View className="dorm-stat">
            <Text className="dorm-stat-label">剩余电量（度）</Text>
            <Text className="dorm-stat-value dorm-stat-value-remaining">
              {electricity?.remaining != null ? electricity.remaining.toFixed(2) : '--'}
            </Text>
          </View>
          <View className="dorm-stat-divider" />
          <View className="dorm-stat">
            <Text className="dorm-stat-label">本月已用（度）</Text>
            <Text className="dorm-stat-value dorm-stat-value-used">
              {monthUsed != null ? monthUsed.toFixed(2) : '--'}
            </Text>
          </View>
        </View>
        <View className="dorm-foot">
          {cookieConfigured === false ? (
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

      {/* 功能列表 */}
      <View className="card profile-list">
        {/* 我的消息：消息图标 + 未读角标（与顶部图标双入口，避免找不到） */}
        <View
          className="profile-item"
          onClick={() => Taro.navigateTo({ url: '/pages/messages/index' })}
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-tongzhi profile-item-icon" />
          </View>
          <Text className="profile-label">我的消息</Text>
          <FeedbackBadge count={msgUnread} />
          <Text className="profile-arrow">›</Text>
        </View>
        {/* 我的课表：跳到课表详情页（周视图，含周次切换/课程卡片），而不是首页 tabBar 的「时间轴」 */}
        <View className="profile-item" onClick={() => Taro.navigateTo({ url: '/pages/coursetable/index' })}>
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-kechengbiao profile-item-icon" />
          </View>
          <Text className="profile-label">我的课表</Text>
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() => Taro.navigateTo({ url: '/pages/favorites/index' })}
        >
          <View className="profile-item-icon-wrap">
            <Text className="profile-item-icon profile-star-icon">{'\u2606'}</Text>
          </View>
          <Text className="profile-label">我的收藏</Text>
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() => Taro.navigateTo({ url: '/pages/feedback/submit/index' })}
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-yijianyufankui profile-item-icon" />
          </View>
          <Text className="profile-label">意见反馈</Text>
          <FeedbackBadge count={feedbackUnread} />
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() => Taro.navigateTo({ url: '/pages/settings/index' })}
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-shezhi profile-item-icon" />
          </View>
          <Text className="profile-label">设置</Text>
          <Text className="profile-arrow">›</Text>
        </View>
      </View>

      <View className="logout-btn" onClick={handleLogout}>
        <Text className="logout-text">退出登录</Text>
      </View>

      <Text className="profile-version">校园宜知行 v1.0.0</Text>
    </View>
  );
}