import { useState } from 'react';
import { View, Text, Textarea, Input, Image } from '@tarojs/components';
import Taro, { useLoad, useDidShow } from '@tarojs/taro';

import * as feedbackApi from '@/api/feedback';
import { API_BASE_URL } from '@/utils/request';
import type { FeedbackType } from '@/types/api';
import FeedbackBadge from '@/components/FeedbackBadge';
import { useFeedbackBadge } from '@/hooks/useFeedbackBadge';
import './index.scss';

/**
 * 意见与反馈 - 提交页
 *
 * 与「消息中心」（管理员 → 学生推送）完全独立，是学生 → 管理员的反向通道。
 * 顶部「我的反馈 ›」可跳转到历史列表。
 *
 * 表单字段：
 * - 类型（必选）：功能异常 / 功能建议 / 咨询求助 / 其他
 * - 内容（必填，≤2000 字）
 * - 联系方式（选填）
 * - 截图（选填，最多 9 张，先上传拿到 URL 再随表单提交）
 */

const TYPE_OPTIONS: { value: FeedbackType; label: string }[] = [
  { value: 'bug', label: '功能异常' },
  { value: 'suggest', label: '功能建议' },
  { value: 'consult', label: '咨询求助' },
  { value: 'other', label: '其他' },
];

const MAX_CONTENT = 2000;
const MAX_IMAGES = 9;

export default function FeedbackSubmitPage() {
  const [type, setType] = useState<FeedbackType>('bug');
  const [content, setContent] = useState('');
  const [contact, setContact] = useState('');
  const [images, setImages] = useState<string[]>([]); // 后端返回的 URL
  const [uploading, setUploading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  // 反馈未读红点（已受理未查看的反馈数）
  const { count: feedbackUnread, refresh: refreshFeedbackBadge } = useFeedbackBadge();

  useLoad(() => {
    Taro.setNavigationBarTitle({ title: '意见反馈' });
    refreshFeedbackBadge();
  });

  // 从详情返回后刷新红点（查看一条即 -1）
  useDidShow(() => {
    refreshFeedbackBadge();
  });

  const goMyList = () => {
    Taro.navigateTo({ url: '/pages/feedback/list/index' });
  };

  const chooseAndUpload = async () => {
    if (uploading) return;
    const remain = MAX_IMAGES - images.length;
    if (remain <= 0) {
      Taro.showToast({ title: `最多上传 ${MAX_IMAGES} 张`, icon: 'none' });
      return;
    }
    try {
      const choosen = await Taro.chooseImage({ count: remain, sizeType: ['compressed'], sourceType: ['album', 'camera'] });
      const temps = choosen.tempFilePaths;
      setUploading(true);
      const urls: string[] = [];
      for (const p of temps) {
        try {
          const url = await feedbackApi.uploadImage(p);
          urls.push(url);
        } catch (e) {
          // 暴露真实原因（原来是笼统的"有图片上传失败"，线上无法定位问题）。
          // 常见：uploadFile 域名未加入小程序白名单 / 图片过大被 nginx 拒绝 / 登录过期
          const msg = (e as Error).message || '图片上传失败';
          Taro.showToast({ title: msg, icon: 'none', duration: 3000 });
        }
      }
      if (urls.length) setImages((prev) => [...prev, ...urls].slice(0, MAX_IMAGES));
    } catch {
      // 用户取消选择，忽略
    } finally {
      setUploading(false);
    }
  };

  const removeImage = (idx: number) => {
    setImages((prev) => prev.filter((_, i) => i !== idx));
  };

  const handleSubmit = async () => {
    if (submitting) return;
    if (!content.trim()) {
      Taro.showToast({ title: '请填写反馈内容', icon: 'none' });
      return;
    }
    if (content.length > MAX_CONTENT) {
      Taro.showToast({ title: `内容不超过 ${MAX_CONTENT} 字`, icon: 'none' });
      return;
    }
    setSubmitting(true);
    try {
      const res = await feedbackApi.create({
        type,
        content: content.trim(),
        contact: contact.trim() || undefined,
        images,
      });
      const id = res?.data?.id;
      Taro.showToast({ title: '提交成功', icon: 'success' });
      // 提交后跳转我的反馈，便于查看处理进度
      setTimeout(() => {
        Taro.redirectTo({ url: `/pages/feedback/list/index${id ? `?highlight=${id}` : ''}` });
      }, 700);
    } catch (e) {
      Taro.showToast({ title: (e as Error).message || '提交失败', icon: 'none' });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <View className="fb-submit-page">
      {/* 顶部：我的反馈入口 */}
      <View className="fb-topbar" onClick={goMyList}>
        <View className="fb-topbar-label">
          <Text className="fb-topbar-text">我的反馈</Text>
          <FeedbackBadge count={feedbackUnread} />
        </View>
        <Text className="fb-topbar-arrow">›</Text>
      </View>

      <View className="fb-form">
        {/* 类型 */}
        <View className="fb-field">
          <Text className="fb-label">
            反馈类型<Text className="fb-required">*</Text>
          </Text>
          <View className="fb-type-grid">
            {TYPE_OPTIONS.map((opt) => (
              <View
                key={opt.value}
                className={`fb-type-chip ${type === opt.value ? 'fb-type-active' : ''}`}
                onClick={() => setType(opt.value)}
              >
                <Text className="fb-type-label">{opt.label}</Text>
              </View>
            ))}
          </View>
        </View>

        {/* 内容 */}
        <View className="fb-field">
          <Text className="fb-label">
            反馈内容<Text className="fb-required">*</Text>
          </Text>
          <View className="fb-textarea-wrap">
            <Textarea
              className="fb-textarea"
              placeholder="请描述您遇到的问题或建议（最多 2000 字）"
              placeholderClass="fb-placeholder"
              maxlength={MAX_CONTENT}
              value={content}
              onInput={(e) => setContent(e.detail.value)}
            />
            <Text className="fb-counter">{content.length}/{MAX_CONTENT}</Text>
          </View>
        </View>

        {/* 联系方式 */}
        <View className="fb-field">
          <Text className="fb-label">联系方式（选填）</Text>
          <Input
            className="fb-input"
            placeholder="手机 / 微信号 / 邮箱"
            placeholderClass="fb-placeholder"
            value={contact}
            onInput={(e) => setContact(e.detail.value)}
          />
        </View>

        {/* 截图 */}
        <View className="fb-field">
          <Text className="fb-label">截图（选填，最多 {MAX_IMAGES} 张）</Text>
          <View className="fb-images">
            {images.map((url, idx) => (
              <View className="fb-img-item" key={url + idx}>
                <Image className="fb-img" src={`${API_BASE_URL}${url}`} mode="aspectFill" />
                <View className="fb-img-del" onClick={() => removeImage(idx)}>
                  <Text className="fb-img-del-x">×</Text>
                </View>
              </View>
            ))}
            {images.length < MAX_IMAGES ? (
              <View className="fb-img-add" onClick={chooseAndUpload}>
                {uploading ? (
                  <Text className="fb-img-add-loading">…</Text>
                ) : (
                  <Text className="fb-img-add-plus">+</Text>
                )}
                <Text className="fb-img-add-text">添加</Text>
              </View>
            ) : null}
          </View>
        </View>
      </View>

      {/* 提交按钮 */}
      <View className="fb-submit-bar">
        <View
          className={`fb-submit-btn ${submitting ? 'fb-submit-disabled' : ''}`}
          onClick={handleSubmit}
        >
          <Text className="fb-submit-text">{submitting ? '提交中…' : '提交反馈'}</Text>
        </View>
      </View>
    </View>
  );
}

export const config = {
  navigationBarTitleText: '意见反馈',
  enablePullDownRefresh: false,
};
