import { useState, useRef } from 'react';
import { View, Text, Image } from '@tarojs/components';
import Taro, { useLoad, useDidShow } from '@tarojs/taro';

import * as electricityApi from '@/api/electricity';
import * as userApi from '@/api/user';
import type { ElectricityCurrent, ElectricityRecord } from '@/types/api';
import dayjs from 'dayjs';
import { logout as logoutApi } from '@/api/auth';
import { useAuthStore } from '@/stores/authStore';
import { useUserStore } from '@/stores/userStore';
import CampusCard from '@/components/CampusCard';
import './index.scss';

/**
 * 我的页（按原型图重做）
 * 结构（自上而下）：
 * - 顶部资料头部（大头像 + 姓名 + 专业年级 + 右上…/二维码）
 * - 校园卡（蓝卡，占位：后端无接口）
 * - 宿舍用电（剩余 + 本月已用，两列）
 * - 功能列表（我的课表/收藏/反馈/设置/退出登录）
 */
export default function ProfilePage() {
  const { user, refreshToken, logout: clearAuth } = useAuthStore();
  const { profile, setProfile } = useUserStore();

  const [statusBarHeight, setStatusBarHeight] = useState(20);
  const [electricity, setElectricity] = useState<ElectricityCurrent | null>(null);
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
        .then((r) => ({ ok: true as const, d: r.data.electricity }))
        .catch(() => ({ ok: false as const, d: null })),
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
  });

  // 电量轻量刷新（后台触发，成功后更新展示值；更新时间显示"访问这一刻"）
  const refreshElectricity = () => {
    electricityApi.refresh().then((r) => {
      const e = r?.data?.electricity;
      if (e) {
        setElectricity(e);
        // 用客户端当前时间作为更新时间（本次请求已确认数据真实性），而非后端爬取时间戳
        setUpdateTime(dayjs().format('YYYY-MM-DD HH:mm:ss'));
      }
    }).catch(() => { /* 刷新失败保留缓存 */ });
  };

  // "我的"是 TabBar 页：切 Tab 离开再回来时页面常驻内存，非首次 onShow 也刷新一次
  const firstShowRef = useRef(true);
  useDidShow(() => {
    if (firstShowRef.current) {
      firstShowRef.current = false;
      return; // 首次进入走 useLoad，不重复
    }
    loadAll();
    refreshElectricity();
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

  const handleMore = () => {
    Taro.showActionSheet({
      itemList: ['消息设置', '帮助反馈', '关于', '退出登录'],
      success: (res) => {
        if (res.tapIndex === 0 || res.tapIndex === 1) {
          Taro.showToast({ title: '功能开发中', icon: 'none' });
          return;
        }
        if (res.tapIndex === 2) {
          Taro.showModal({
            title: '关于',
            content: '校园宜知行 · 校园信息聚合与智能推送系统\n微信小程序客户端',
            showCancel: false,
          });
          return;
        }
        handleLogout();
      },
    });
  };

  const name = profile?.real_name || user?.username || '同学';
  const majorGrade = [profile?.major, profile?.grade ? `${profile.grade}级` : '']
    .filter(Boolean)
    .join(' · ');

  return (
    <View
      className="page profile-page"
      style={{ paddingTop: `${statusBarHeight + 44}px` }}
    >
      {/* 资料头部：头像 + 姓名 + 专业年级 + 右上…/二维码（背景由 .profile-page CSS class 的径向渐变提供） */}
      <View className="profile-header">
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
        <View className="profile-header-actions">
          <View
            className="profile-qr"
            onClick={() => Taro.showToast({ title: '二维码开发中', icon: 'none' })}
          >
            <Text className="iconfont icon-erweima profile-qr-icon" />
          </View>
          <View className="profile-more" onClick={handleMore}>
            <Text className="iconfont icon-more profile-more-icon" />
          </View>
        </View>
      </View>

      {/* 校园卡（蓝卡，占位：后端无接口） */}
      <CampusCard studentNumber={profile?.student_number} />

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
          <Text className="dorm-foot-time">
            {updateTime ? `更新时间：${updateTime}` : '暂无更新'}
          </Text>
          <View
            className="dorm-foot-btn"
            onClick={() => Taro.navigateTo({ url: '/pages/electricity/index' })}
          >
            <Text>用电详情</Text>
          </View>
        </View>
      </View>

      {/* 功能列表 */}
      <View className="card profile-list">
        <View className="profile-item" onClick={() => Taro.switchTab({ url: '/pages/schedule/index' })}>
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-kechengbiao profile-item-icon" />
          </View>
          <Text className="profile-label">我的课表</Text>
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() => Taro.showToast({ title: '功能开发中', icon: 'none' })}
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-shoucang profile-item-icon" />
          </View>
          <Text className="profile-label">我的收藏</Text>
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() => Taro.showToast({ title: '功能开发中', icon: 'none' })}
        >
          <View className="profile-item-icon-wrap">
            <Text className="iconfont icon-yijianyufankui profile-item-icon" />
          </View>
          <Text className="profile-label">意见反馈</Text>
          <Text className="profile-arrow">›</Text>
        </View>
        <View
          className="profile-item"
          onClick={() => Taro.showToast({ title: '功能开发中', icon: 'none' })}
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

      <Text className="profile-version">校园宜知行 v0.1.0</Text>
    </View>
  );
}