/**
 * 身份绑定页
 *
 * 登录后若未通过管理员预录名单完成身份绑定，所有业务请求会收到
 * 403（code=STUDENT_NOT_BOUND），由请求层统一 reLaunch 到本页。
 *
 * 流程：选择学校（含模糊干扰项）→ 输入学号、班级 → 提交 →
 * 三项命中预录名单（启用中）即绑定成功 → 回到首页。
 * 未命中：提示联系管理员确认名单（筛除无关人员）。
 */
import { useEffect, useState } from 'react';
import { View, Text, Input } from '@tarojs/components';
import Taro from '@tarojs/taro';

import * as userApi from '@/api/user';
import { useUserStore } from '@/stores/userStore';
import './index.scss';

export default function BindPage() {
  const { setProfile } = useUserStore();

  const [schools, setSchools] = useState<string[]>([]);
  const [school, setSchool] = useState('');
  const [studentNumber, setStudentNumber] = useState('');
  const [className, setClassName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [loading, setLoading] = useState(true);

  // 挂载时：拉学校列表；若已绑定（重复进入），直接回首页
  useEffect(() => {
    (async () => {
      try {
        const [schoolsRes, statusRes] = await Promise.all([
          userApi.getSchools(),
          userApi.getBindStatus(),
        ]);
        if (schoolsRes.status === 'success') {
          setSchools(schoolsRes.schools || []);
        }
        if (statusRes.status === 'success' && statusRes.bound) {
          Taro.reLaunch({ url: '/pages/home/index' });
          return;
        }
      } catch {
        // 网络异常时仍允许停留在绑定页重试
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const handleSubmit = async () => {
    if (submitting) return;
    const s = school.trim();
    const num = studentNumber.trim();
    const cls = className.trim();
    if (!s) {
      Taro.showToast({ title: '请选择学校', icon: 'none' });
      return;
    }
    if (!num) {
      Taro.showToast({ title: '请输入学号', icon: 'none' });
      return;
    }
    if (!cls) {
      Taro.showToast({ title: '请输入班级', icon: 'none' });
      return;
    }
    setSubmitting(true);
    try {
      const res = await userApi.bindStudent({
        school: s,
        student_number: num,
        class_name: cls,
      });
      if (res.status === 'success' && res.bound) {
        if (res.profile) setProfile(res.profile);
        Taro.showToast({ title: '绑定成功', icon: 'success' });
        setTimeout(() => Taro.reLaunch({ url: '/pages/home/index' }), 600);
      } else {
        Taro.showToast({ title: res.message || '绑定失败，请重试', icon: 'none' });
      }
    } catch (e) {
      const msg = (e as { message?: string })?.message || '绑定失败，请重试';
      Taro.showToast({ title: msg, icon: 'none' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View className="bind-page">
      <View className="bind-card">
        <Text className="bind-title">身份认证</Text>
        <Text className="bind-desc">
          请选择学校并填写学号、班级完成身份认证。信息须与学校登记一致，仅限本校在读学生使用。
        </Text>

        {/* 学校选择（模糊选项，正校必须保留） */}
        <Text className="bind-label">学校</Text>
        <View className="bind-schools">
          {schools.map((s) => (
            <View
              key={s}
              className={`bind-school-chip${school === s ? ' bind-school-chip-active' : ''}`}
              onClick={() => setSchool(s)}
            >
              <Text className={school === s ? 'bind-school-text-active' : 'bind-school-text'}>
                {s}
              </Text>
            </View>
          ))}
          {!loading && schools.length === 0 && (
            <Text className="bind-school-empty">学校列表加载失败，请下拉重试</Text>
          )}
        </View>

        {/* 学号 / 班级 */}
        <Text className="bind-label">学号</Text>
        <View className="bind-input-row">
          <Input
            className="bind-input"
            value={studentNumber}
            placeholder="请输入学号"
            placeholderClass="bind-placeholder"
            maxlength={30}
            onInput={(e) => setStudentNumber(e.detail.value)}
          />
        </View>

        <Text className="bind-label">班级</Text>
        <View className="bind-input-row">
          <Input
            className="bind-input"
            value={className}
            placeholder="请输入班级，如：计算机2301"
            placeholderClass="bind-placeholder"
            maxlength={30}
            onInput={(e) => setClassName(e.detail.value)}
          />
        </View>

        <View
          className={`bind-submit${submitting ? ' bind-submit-disabled' : ''}`}
          onClick={handleSubmit}
        >
          <Text className="bind-submit-text">{submitting ? '提交中…' : '提交认证'}</Text>
        </View>

        <Text className="bind-hint">
          如无法通过认证，请联系管理员确认名单信息
        </Text>
      </View>
    </View>
  );
}
