import { useState, useEffect, useRef } from 'react';
import { View, Text } from '@tarojs/components';
import Taro, { useLoad, useDidShow, usePullDownRefresh, stopPullDownRefresh } from '@tarojs/taro';

import { setTabIndex } from '@/utils/tabBarState';

import * as weatherApi from '@/api/weather';
import * as scheduleApi from '@/api/schedule';
import * as userApi from '@/api/user';
import type { ScheduleCourse, WeatherNow } from '@/types/api';
import { greeting, todayText } from '@/utils/date';
import { useAuthStore } from '@/stores/authStore';
import { useUserStore } from '@/stores/userStore';
import WeatherCard from '@/components/WeatherCard';
import CourseCard from '@/components/CourseCard';
import NoticeCard from '@/components/NoticeCard';
import QuickAccess from '@/components/QuickAccess';
import LoginModal from '@/components/LoginModal';
import { toastLoginRequired } from '@/hooks/useLoginGuard';
import { useBindStatusWatcher } from '@/hooks/useBindStatusWatcher';
import { isBindGuideActive, BIND_GUIDE_FINISHED_EVENT } from '@/utils/bindGuard';
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import IconArrow from '@/components/IconArrow';
import { splitCoursesToBigClasses } from '@/utils/scheduleBigClass';
import './index.scss';

/** 首页常用功能中免登录的公开项（天气/公告后端已放开匿名访问） */
const PUBLIC_QUICK_KEYS = ['notice', 'weather'];

/**
 * 首页
 * 自定义导航栏：顶部"校园宜知行"左对齐粗体大字（navigationStyle: custom）
 * 头部（原型图布局）：问候+日期 + 天气小卡 并排
 * 主体：常用功能 → 今日课程 → 宿舍电量 → 校园通知
 */
export default function HomePage() {
  const [loading, setLoading] = useState(true);
  const [statusBarHeight, setStatusBarHeight] = useState(20);
  const [weather, setWeather] = useState<WeatherNow | null>(null);
  const [tempRange, setTempRange] = useState<{ min: number; max: number } | null>(null);
  const [courses, setCourses] = useState<ScheduleCourse[]>([]);

  const { user, refreshToken, logout: clearAuth, isLoggedIn } = useAuthStore();
  const { profile, setProfile } = useUserStore();
  const [showLogin, setShowLogin] = useState(false);
  // 本轮登录态内是否已拉取过需登录数据（今日课程/资料）：
  // - 防止事件/生命周期重复触发时反复请求同一批接口；
  // - 登出（手动/会话过期/被解绑回收）时重置，保证重新登录后能再次自动拉取。
  const privateLoadedRef = useRef(false);
  // 身份状态主动监察：管理员解绑后清空身份缓存并跳绑定页（承接「解绑/收回身份」）
  useBindStatusWatcher();

  const loadAll = async () => {
    setLoading(true);
    // 需登录数据（今日课程/资料）的拉取条件：已登录且不在绑定引导期。
    // 游客（isLoggedIn=false）打了必 401、引导期（登录成功未绑定）打了必 403，
    // 都是纯浪费 + 刷错误噪音，直接跳过，交由登录引导占位/事件补拉。
    const privateReady = isLoggedIn && !isBindGuideActive();
    const [wRes, hRes, sRes, pRes] = await Promise.all([
      weatherApi
        .getCurrent()
        .then((r) => ({ ok: true as const, d: r.data.weather }))
        .catch(() => ({ ok: false as const, d: null })),
      weatherApi
        .getHourly()
        .then((r) => {
          const temps = r.data.hourly
            .map((h) => Number(h.temp))
            .filter((n) => Number.isFinite(n));
          const range =
            temps.length >= 2 ? { min: Math.min(...temps), max: Math.max(...temps) } : null;
          return { ok: true as const, d: range };
        })
        .catch(() => ({ ok: false as const, d: null })),
      // 今日课程需登录：游客或"登录成功未绑定的引导期"不调用（绑定期发了必然 403，
      // 纯浪费 + 刷 403 噪音），交由卡片登录引导占位
      privateReady
        ? scheduleApi
            .getToday()
            .then((r) => ({ ok: true as const, d: r.data.courses }))
            .catch(() => ({ ok: false as const, d: [] as ScheduleCourse[] }))
        : Promise.resolve({ ok: true as const, d: [] as ScheduleCourse[] }),
      // 个人资料需登录：游客/绑定引导期跳过（解绑后 403 触发跳绑定页、缓存清空）
      privateReady
        ? userApi
            .getProfile()
            .then((r) => ({ ok: true as const, d: r.profile }))
            .catch(() => ({ ok: false as const, d: null }))
        : Promise.resolve({ ok: true as const, d: null }),
    ]);
    setWeather(wRes.ok ? wRes.d : null);
    setTempRange(hRes.ok ? hRes.d : null);
    setCourses(sRes.ok ? sRes.d : []);
    if (pRes.ok && pRes.d) setProfile(pRes.d);
    // 本轮登录态的需登录数据已拉过（无论成败）：后续 bindGuide 事件不再重复补拉，
    // 失败场景由用户下拉刷新兜底重试
    if (privateReady) privateLoadedRef.current = true;
    setLoading(false);
  };

  useLoad(() => {
    // 自定义导航栏：读取状态栏高度，避免标题被刘海/状态栏遮挡
    try {
      const info = Taro.getWindowInfo();
      if (info.statusBarHeight) setStatusBarHeight(info.statusBarHeight);
    } catch {
      // 兜底 20
    }
    loadAll();
  });

  // 首页是 TabBar 第 0 项：每次显示广播自身下标，保证 TabBar 选中态与任意进入路径一致
  useDidShow(() => {
    setTabIndex(0);
  });

  usePullDownRefresh(async () => {
    await loadAll();
    stopPullDownRefresh();
  });

  // 登录态变化（游客 → 已登录，如从登录页返回）：重新拉取需登录的内容（今日课程/资料）。
  // 注意：登录瞬间处于"绑定引导期"（登录页 setAuth 后同步 beginBindGuide），此处拉取
  // 会被 loadAll 内的 privateReady 拦下且引导期结束后 isLoggedIn 不再变化、effect 不会
  // 重发——改由下方 BIND_GUIDE_FINISHED_EVENT 监听在「登录 + 绑定双确认」后补拉。
  // 登出（手动 / 会话过期 / 被解绑回收）：清空旧账号的今日课程并重置标记，
  // 一来游客态不残留上一账号数据，二来重新登录后事件能再次触发自动拉取。
  useEffect(() => {
    if (isLoggedIn) {
      if (!isBindGuideActive()) loadAll();
    } else {
      privateLoadedRef.current = false;
      setCourses([]);
    }
  }, [isLoggedIn]);

  // 绑定引导期结束（登录页确认已绑定 / 绑定页绑定成功）→ 自动补拉今日课程/资料：
  // 修复"登录后今日课程为空、需手动下拉刷新"的问题；本轮已拉过（privateLoadedRef）
  // 则跳过，避免重复请求。依赖 [isLoggedIn]：登录态变化时以最新闭包重新注册监听，
  // 保证 loadAll 读到正确的 isLoggedIn。
  useEffect(() => {
    const onBoundConfirmed = () => {
      if (!privateLoadedRef.current) loadAll();
    };
    Taro.eventCenter.on(BIND_GUIDE_FINISHED_EVENT, onBoundConfirmed);
    return () => {
      Taro.eventCenter.off(BIND_GUIDE_FINISHED_EVENT, onBoundConfirmed);
    };
  }, [isLoggedIn]);

  // 两节为一节大课：把后端合并的整段课程（如 5-8节）按每 2 节拆成独立大课展示
  const bigClassCourses = splitCoursesToBigClasses(courses);
  const sortedCourses = [...bigClassCourses].sort(
    (a, b) => (a._timeInfo?.start_ts || 0) - (b._timeInfo?.start_ts || 0),
  );

  return (
    <View className="page home-page" style={{ paddingTop: `${statusBarHeight}px` }}>
      {/* 顶部蓝白斜渐变溶解背景（绝对定位，覆盖到常用功能卡片位置） */}
      <View className="home-bg" />

      <View className="home-content">
        {/* 自定义导航栏标题：左对齐粗体大字 */}
        <Text className="home-nav-title">校园宜知行</Text>

        {/* 头部：问候 + 天气小卡 并排（原型图布局） */}
        <View className="home-hero">
          <View className="hero-text">
            <Text className="hero-greeting">
              {greeting()}，{profile?.nickname || profile?.real_name || user?.username || '同学'}
            </Text>
            <Text className="hero-date">{todayText()}</Text>
          </View>
          <View>
            <WeatherCard
              weather={weather}
              tempRange={tempRange}
              loading={loading}
              error={weather === null}
              onRetry={loadAll}
            />
          </View>
        </View>

        {loading ? (
          <LoadingState text="正在加载今日信息…" />
        ) : (
          <>
            {/* 常用功能 8 宫格 */}
            <QuickAccess
              requireLogin={!isLoggedIn}
              publicKeys={PUBLIC_QUICK_KEYS}
              // 游客点受限宫格项：仅气泡提示（登录入口由显式登录卡片承担）
              onLogin={toastLoginRequired}
            />

            {/* 今日课程（需登录：游客展示登录引导占位） */}
            <View className="card">
              <View className="card-header">
                <Text className="card-title">今日课程</Text>
                <View
                  className="card-more card-more-btn"
                  onClick={() => (isLoggedIn ? Taro.navigateTo({ url: '/pages/coursetable/index' }) : toastLoginRequired())}
                >
                  <Text className="card-more-text">全部课程</Text>
                  <IconArrow className="card-more-arrow" size="md" />
                </View>
              </View>
              {isLoggedIn ? (
                sortedCourses.length === 0 ? (
                  <EmptyState title="今天没有课程" desc="好好休息一下吧" />
                ) : (
                  sortedCourses.map((c) => (
                    <CourseCard
                      key={c.schedule_id}
                      course={c}
                      onClick={() => {
                        // 拆分的合成 id 形如 "X#p5-6"，详情页需要原始 id
                        const originalId = c.schedule_id.split('#p')[0];
                        // 拆分段（5-6 / 7-8）把本段节次带给详情页，否则详情会显示整段 5-8
                        const pnums = Array.isArray(c.periods) ? c.periods : [];
                        const periodParam =
                          c.schedule_id.includes('#p') && pnums.length
                            ? `&periods=${pnums.join(',')}`
                            : '';
                        Taro.navigateTo({
                          url: `/pages/coursedetail/index?id=${originalId}${periodParam}`,
                        });
                      }}
                    />
                  ))
                )
              ) : (
                <View className="home-login-tip" onClick={() => setShowLogin(true)}>
                  <Text className="home-login-tip-text">登录后查看今日课程</Text>
                  <IconArrow className="home-login-tip-arrow" size="md" />
                </View>
              )}
            </View>

            {/* 校园通知（公开，游客可浏览） */}
            <NoticeCard />
          </>
        )}
      </View>

      {/* 游客访问受限功能：弹出登录引导，确定跳转登录页 */}
      <LoginModal visible={showLogin} onCancel={() => setShowLogin(false)} />
    </View>
  );
}