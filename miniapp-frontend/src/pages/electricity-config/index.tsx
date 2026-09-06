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
      Taro.showToast({ title: '请先粘贴鉴权信息', icon: 'none' });
      return;
    }
    setTesting(true);
    try {
      const res = await electricityApi.testCookie(value);
      const { valid, reason } = res?.data || { valid: false, reason: '' };
      if (valid) {
        Taro.showToast({ title: '鉴权信息有效', icon: 'success' });
      } else {
        Taro.showToast({ title: reason || '鉴权信息无效', icon: 'none', duration: 2500 });
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
      Taro.showToast({ title: '请先粘贴鉴权信息', icon: 'none' });
      return;
    }
    if (value.length > MAX_LEN) {
      Taro.showToast({ title: `内容过长（上限 ${MAX_LEN} 字符）`, icon: 'none' });
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
      {/* 当前配置状态：左侧色条 + 标题 + 脱敏预览 */}
      <View className={`ecfg-status${configured ? '' : ' empty'}`}>
        <View className="ecfg-status-main">
          <Text className="ecfg-status-title">
            {configured ? '已配置电表接入信息' : '尚未配置电表接入信息'}
          </Text>
          {configured ? (
            <Text className="ecfg-status-preview">当前：{preview}</Text>
          ) : (
            <Text className="ecfg-status-preview empty">配置后可自动采集您宿舍的电量数据</Text>
          )}
        </View>
      </View>

      {/* 获取说明：编号方块 + 段落 */}
      <View className="ecfg-card">
        <Text className="ecfg-card-title">如何取得接入信息</Text>
        <View className="ecfg-steps">
          <View className="ecfg-step">
            <Text className="ecfg-step-num">1</Text>
            <Text className="ecfg-step-text">
              在您用来缴纳宿舍电费的校内服务里，先打开一次您宿舍的电费查询，确认能正常看到用电数据
            </Text>
          </View>
          <View className="ecfg-step">
            <Text className="ecfg-step-num">2</Text>
            <Text className="ecfg-step-text">
              打开电脑或手机的调试面板，把刚才那次电费查询产生的数据记录调出来
            </Text>
          </View>
          <View className="ecfg-step">
            <Text className="ecfg-step-num">3</Text>
            <Text className="ecfg-step-text">
              在记录里找到电费查询那条请求，把请求附带的整段较长的字符一并复制
            </Text>
          </View>
          <View className="ecfg-step">
            <Text className="ecfg-step-num">4</Text>
            <Text className="ecfg-step-text">粘贴到下方输入框，点击「测试」，有效后点击「保存」</Text>
          </View>
        </View>
        <Text className="ecfg-warn">
          该信息仅用于自动读取您本人宿舍的电量，只会保存在您自己的账号下，请勿外传
        </Text>
      </View>

      {/* 输入区：标题 + 字数 + 细边白底输入框（焦点蓝边） */}
      <View className="ecfg-card">
        <View className="ecfg-input-head">
          <Text className="ecfg-card-title no-margin">接入信息</Text>
          <Text className="ecfg-counter">{cookie.length}/{MAX_LEN}</Text>
        </View>
        <View className="ecfg-textarea-wrap">
          <Textarea
            className="ecfg-textarea"
            placeholder="粘贴完整的接入字符…"
            placeholderClass="ecfg-placeholder"
            maxlength={MAX_LEN}
            value={cookie}
            onInput={(e) => setCookie(e.detail.value)}
          />
        </View>
      </View>

      {/* 底部固定按钮栏：次按钮文字按钮 + 主按钮实色（无蓝色光晕） */}
      <View className="ecfg-actionbar">
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
