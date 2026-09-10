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
import { useCallback, useEffect, useState } from 'react';
import { View, Text, Input, Picker } from '@tarojs/components';
import Taro, { useUnload } from '@tarojs/taro';

import * as userApi from '@/api/user';
import { ApiError } from '@/utils/request';
import { finishBindGuide, cancelBindGuide } from '@/utils/bindGuard';
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
  const [schoolError, setSchoolError] = useState(false);
  const [schoolAuthError, setSchoolAuthError] = useState(false);

  // 加载学校列表 + 绑定状态；两个请求独立 catch，避免一个失败导致另一个结果也被丢弃
  const loadData = useCallback(async () => {
    setLoading(true);
    setSchoolError(false);
    setSchoolAuthError(false);

    try {
      const schoolsRes = await userApi.getSchools();
      if (schoolsRes.status === 'success') {
        setSchools(schoolsRes.schools || []);
      }
    } catch (err) {
      console.error('[BindPage] getSchools failed:', err);
      setSchoolError(true);
      // 401/403 = 未登录或会话失效，引导去登录，而非伪装成网络问题
      const apiErr = err as ApiError;
      setSchoolAuthError(apiErr instanceof ApiError && (apiErr.code === 401 || apiErr.code === 403));
      Taro.showToast({ title: '学校列表加载失败', icon: 'none' });
    }

    try {
      const statusRes = await userApi.getBindStatus();
      if (statusRes.status === 'success' && statusRes.bound) {
        // 已绑定用户误入绑定页（如登录页查绑定状态网络抖动失败被当作未绑定）：
        // 先结束引导期再跳走，既清除标记、又广播事件让首页补拉需登录数据，
        // 否则标记残留会持续吞掉后续真正的 403 降级，且今日课程无人补拉
        finishBindGuide();
        Taro.switchTab({ url: '/pages/home/index' });
        return;
      }
    } catch {
      // 绑定状态查询失败不阻断页面，允许用户停留在绑定页重试
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // 离开绑定页（无论成功跳走还是用户返回）：结束/取消绑定引导期，
  // 避免标记残留、把后续真正的 403（如会话中被解绑）也误判为"引导期"而吞掉降级。
  useUnload(() => {
    cancelBindGuide();
  });

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
        finishBindGuide();
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
      <View className="bind-intro">
        <Text className="bind-intro-text">选择所在学校并填写认证信息</Text>
      </View>

      <View className="bind-group">
        {/* 学校：分组行，点击弹原生下拉 */}
        <View className="bind-row">
          <Text className="bind-row-label">学校</Text>
          {schools.length > 0 ? (
            /* 外层 View 承担布局（撑满剩余宽度 + 内容靠右）：原生 picker 宿主节点
               内部自带包裹结构，直接在 picker 上做 flex 布局不生效 */
            <View className="bind-row-picker-wrap">
              <Picker
                mode="selector"
                range={schools}
                value={school ? Math.max(0, schools.indexOf(school)) : 0}
                onChange={(e) => setSchool(schools[Number(e.detail.value)])}
              >
                <View className="bind-row-value-wrap">
                  <Text className={school ? 'bind-row-value' : 'bind-row-placeholder'}>
                    {school || '请选择学校'}
                  </Text>
                  <Text className="iconfont icon-jinru bind-row-arrow" />
                </View>
              </Picker>
            </View>
          ) : !loading ? (
            schoolAuthError ? (
              <Text
                className="bind-school-empty bind-school-login"
                onClick={() => Taro.navigateTo({ url: '/pages/login/index' })}
              >
                登录已失效，请先登录
              </Text>
            ) : schoolError ? (
              <Text className="bind-school-empty" onClick={() => loadData()}>
                加载失败，点击重试
              </Text>
            ) : (
              <Text className="bind-school-empty">暂无学校选项，请联系管理员</Text>
            )
          ) : null}
        </View>

        <View className="bind-row-divider" />

        {/* 学号 */}
        <View className="bind-row">
          <Text className="bind-row-label">学号</Text>
          <Input
            className="bind-row-input"
            value={studentNumber}
            placeholder="请输入学号"
            placeholderClass="bind-row-placeholder"
            maxlength={30}
            onInput={(e) => setStudentNumber(e.detail.value)}
          />
        </View>

        <View className="bind-row-divider" />

        {/* 绑定码 */}
        <View className="bind-row">
          <Text className="bind-row-label">绑定码</Text>
          <Input
            className="bind-row-input bind-code-input"
            value={bindCode}
            placeholder="请输入绑定码"
            placeholderClass="bind-row-placeholder"
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

      <Text className="bind-footnote">绑定码由管理员发放，一次性有效</Text>
    </View>
  );
}
