import { useState } from 'react';
import { View, Text } from '@tarojs/components';
import Taro, { useLoad, usePullDownRefresh, stopPullDownRefresh } from '@tarojs/taro';

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
import LoadingState from '@/components/LoadingState';
import EmptyState from '@/components/EmptyState';
import './index.scss';

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

  const { user, refreshToken, logout: clearAuth } = useAuthStore();
  const { profile, setProfile } = useUserStore();

  const loadAll = async () => {
    setLoading(true);
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
      scheduleApi
        .getToday()
        .then((r) => ({ ok: true as const, d: r.data.courses }))
        .catch(() => ({ ok: false as const, d: [] as ScheduleCourse[] })),
      !profile
        ? userApi
            .getProfile()
            .then((r) => ({ ok: true as const, d: r.profile }))
            .catch(() => ({ ok: false as const, d: null }))
        : Promise.resolve({ ok: true as const, d: profile }),
    ]);
    setWeather(wRes.ok ? wRes.d : null);
    setTempRange(hRes.ok ? hRes.d : null);
    setCourses(sRes.ok ? sRes.d : []);
    if (pRes.ok && pRes.d) setProfile(pRes.d);
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

  usePullDownRefresh(async () => {
    await loadAll();
    stopPullDownRefresh();
  });

  const sortedCourses = [...courses].sort(
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
              {greeting()}，{profile?.real_name || user?.username || '同学'}
            </Text>
            <Text className="hero-date">{todayText()}</Text>
          </View>
          <View onClick={() => Taro.navigateTo({ url: '/pages/weather/index' })}>
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
            <QuickAccess />

            {/* 今日课程 */}
            <View className="card">
              <View className="card-header">
                <Text className="card-title">今日课程</Text>
                <View
                  className="card-more card-more-btn"
                  onClick={() => Taro.navigateTo({ url: '/pages/coursetable/index' })}
                >
                  <Text className="iconfont icon-kechengbiao card-more-icon" />
                  <Text className="card-more-text">全部课程</Text>
                  <Text className="card-more-arrow">›</Text>
                </View>
              </View>
{sortedCourses.length === 0 ? (
              <EmptyState title="今天没有课程" desc="好好休息一下吧" />
            ) : (
              sortedCourses.map((c) => <CourseCard key={c.schedule_id} course={c} />)
            )}
          </View>

          {/* 校园通知（后端无接口，占位） */}
          <NoticeCard />
          </>
        )}
      </View>
    </View>
  );
}