import { useState } from 'react';
import { View, Text, Textarea } from '@tarojs/components';
import Taro, { useLoad } from '@tarojs/taro';

import * as electricityApi from '@/api/electricity';
import './index.scss';

/**
 * 电表配置页
 *
 * 背景：每个宿舍有独立的电表，系统无法自动获取爬虫 Cookie，
 * 由学生本人粘贴自己宿舍电表的 Cookie 后，后端定时任务才为其独立爬取。
 *
 * 设计：受控表单 + 显式「测试 / 保存」按钮（沿用账号设置页交互约定）：
 * - 测试：POST /electricity/cookie/test（不落库，仅检测有效性）
 * - 保存：PUT /electricity/cookie（写入本人 student_profiles.electricity_cookie）
 * - 已配置时展示脱敏预览（前4后2），不回填完整 Cookie（敏感信息）
 */

const MAX_LEN = 4096;

export default function ElectricityConfigPage() {
  const [cookie, setCookie] = useState('');
  const [configured, setConfigured] = useState(false);
  const [preview, setPreview] = useState('');
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);

  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '电表配置' });
    loadConfig();
  });

  const loadConfig = async () => {
    try {
      const res = await electricityApi.getCookieConfig();
      setConfigured(!!res?.data?.configured);
      setPreview(res?.data?.cookie_preview || '');
    } catch {
      /* 拉取失败不阻塞输入 */
    }
  };

  const handleTest = async () => {
    if (testing) return;
    const value = cookie.trim();
    if (!value) {
      Taro.showToast({ title: '请先粘贴 Cookie', icon: 'none' });
      return;
    }
    setTesting(true);
    try {
      const res = await electricityApi.testCookie(value);
      const { valid, reason } = res?.data || { valid: false, reason: '' };
      if (valid) {
        Taro.showToast({ title: 'Cookie 有效', icon: 'success' });
      } else {
        Taro.showToast({ title: reason || 'Cookie 无效', icon: 'none', duration: 2500 });
      }
    } catch (e) {
      Taro.showToast({ title: (e as Error).message || '测试失败', icon: 'none' });
    } finally {
      setTesting(false);
    }
  };

  const handleSave = async () => {
    if (saving) return;
    const value = cookie.trim();
    if (!value) {
      Taro.showToast({ title: '请先粘贴 Cookie', icon: 'none' });
      return;
    }
    if (value.length > MAX_LEN) {
      Taro.showToast({ title: `Cookie 过长（上限 ${MAX_LEN} 字符）`, icon: 'none' });
      return;
    }
    setSaving(true);
    try {
      await electricityApi.saveCookie(value);
      Taro.showToast({ title: '已保存', icon: 'success' });
      // 延迟返回，让 toast 完整显示
      setTimeout(() => Taro.navigateBack(), 600);
    } catch (e) {
      Taro.showToast({ title: (e as Error).message || '保存失败', icon: 'none' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <View className="ecfg-page">
      {/* 当前配置状态 */}
      <View className="ecfg-card">
        <View className="ecfg-status-row">
          <Text className={`ecfg-status-dot${configured ? '' : ' warn'}`} />
          <Text className={`ecfg-status-text ${configured ? 'ok' : 'empty'}`}>
            {configured ? '已配置电表 Cookie' : '尚未配置电表 Cookie'}
          </Text>
        </View>
        {configured ? (
          <Text className="ecfg-preview">当前：{preview}</Text>
        ) : (
          <Text className="ecfg-preview empty">配置后可自动采集您宿舍的电量数据</Text>
        )}
      </View>

      {/* 获取说明 */}
      <View className="ecfg-card">
        <Text className="ecfg-card-title">如何获取 Cookie</Text>
        <Text className="ecfg-step">1. 在电脑浏览器中登录学校电表查询系统，进入您宿舍的电表页面</Text>
        <Text className="ecfg-step">2. 按 F12 打开开发者工具，切换到「网络」面板</Text>
        <Text className="ecfg-step">3. 刷新页面，找到任意请求，在「请求头」中复制 Cookie 一行的完整内容</Text>
        <Text className="ecfg-step">4. 粘贴到下方输入框，点击「测试」，有效后点击「保存」</Text>
        <Text className="ecfg-warn">Cookie 含您的登录凭证，仅保存在您自己的账号下，请勿分享给他人</Text>
      </View>

      {/* 输入区 */}
      <View className="ecfg-card">
        <View className="ecfg-input-head">
          <Text className="ecfg-card-title">Cookie</Text>
          <Text className="ecfg-counter">{cookie.length}/{MAX_LEN}</Text>
        </View>
        <Textarea
          className="ecfg-textarea"
          placeholder="粘贴完整的 Cookie 字符串…"
          placeholderClass="ecfg-placeholder"
          maxlength={MAX_LEN}
          value={cookie}
          onInput={(e) => setCookie(e.detail.value)}
        />
      </View>

      {/* 操作按钮 */}
      <View className="ecfg-btns">
        <View
          className={`ecfg-btn ecfg-btn-ghost${testing ? ' ecfg-btn-disabled' : ''}`}
          onClick={handleTest}
        >
          <Text className="ecfg-btn-text-ghost">{testing ? '测试中…' : '测试'}</Text>
        </View>
        <View
          className={`ecfg-btn ecfg-btn-primary${saving ? ' ecfg-btn-disabled' : ''}`}
          onClick={handleSave}
        >
          <Text className="ecfg-btn-text-primary">{saving ? '保存中…' : '保存'}</Text>
        </View>
      </View>
    </View>
  );
}

export const config = {
  navigationBarTitleText: '电表配置',
  enablePullDownRefresh: false,
};
