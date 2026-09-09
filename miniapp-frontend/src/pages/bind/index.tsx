/**
 * 身份绑定页
 *
 * 进入本页的两条路径：
 * 1) 登录成功后，登录页 `handleLogin` 检测到未绑定，用 `redirectTo` 替换登录页进入本页
 *    （登录页随之消失，原生「< 返回」回到上一页而非"已登录的登录页"）；
 * 2) 用户在会话中被管理员解绑后，Tab 页 `useBindStatusWatcher` 降级为游客态，
 *    用户需重新登录并再次进入本页完成认证。
 * 请求层（`utils/request.ts`）命中 403 STUDENT_NOT_BOUND 时**不再自动跳转**，
 * 只清空本地身份缓存并抛出错误，由调用方按游客态 / 登录引导处理，避免绑定页叠加。
 *
 * 流程：选择学校 → 输入学号、绑定码 → 提交 → 命中预录名单（启用中，
 * 且绑定码匹配、未核销）即绑定成功 → 回到首页。
 * 班级/学院/专业由名单所在组织树继承写入资料，学生无需填写。
 * 绑定码由管理员生成后私下发放（一次性，绑定即失效）。
 *
 * 合规：使用 WeChat 原生标准顶栏（左侧自动 `< 返回`、居中标题），
 * 不在页面内自绘任何拒绝/退出入口。页面内不再重复顶栏标题。
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
  const [bindCode, setBindCode] = useState('');
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
          Taro.switchTab({ url: '/pages/home/index' });
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
    const code = bindCode.trim();
    if (!s) {
      Taro.showToast({ title: '请选择学校', icon: 'none' });
      return;
    }
    if (!num) {
      Taro.showToast({ title: '请输入学号', icon: 'none' });
      return;
    }
    if (!code) {
      Taro.showToast({ title: '请输入绑定码', icon: 'none' });
      return;
    }
    setSubmitting(true);
    try {
      const res = await userApi.bindStudent({
        school: s,
        student_number: num,
        bind_code: code,
      });
      if (res.status === 'success' && res.bound) {
        if (res.profile) setProfile(res.profile);
        Taro.showToast({ title: '绑定成功', icon: 'success' });
        setTimeout(() => Taro.switchTab({ url: '/pages/home/index' }), 600);
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
      <View className="bind-head">
        <Text className="bind-intro">
          验证学生身份后可接入课程、电费等校园服务。绑定码由管理员发放。
        </Text>
      </View>

      <View className="bind-form">
        {/* 学校选择 */}
        <View className="bind-field">
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
              <Text className="bind-school-empty">暂无学校选项，请联系管理员</Text>
            )}
          </View>
        </View>

        {/* 学号 */}
        <View className="bind-field">
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
        </View>

        {/* 绑定码 */}
        <View className="bind-field">
          <Text className="bind-label">绑定码</Text>
          <View className="bind-input-row">
            <Input
              className="bind-input bind-code-input"
              value={bindCode}
              placeholder="请输入 8 位绑定码"
              placeholderClass="bind-placeholder"
              maxlength={8}
              onInput={(e) => setBindCode(e.detail.value.toUpperCase())}
            />
          </View>
        </View>

        <View
          className={`bind-submit${submitting ? ' bind-submit-disabled' : ''}`}
          hoverClass="bind-submit-hover"
          onClick={handleSubmit}
        >
          <Text className="bind-submit-text">{submitting ? '提交中…' : '确认绑定'}</Text>
        </View>

        <Text className="bind-hint">
          绑定码一次性有效，由管理员发放；遗失可联系管理员重置
        </Text>
      </View>
    </View>
  );
}
