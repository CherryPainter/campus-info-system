import { useState, useEffect } from 'react';
import { View, Text, RichText, ScrollView, Image } from '@tarojs/components';
import Taro, { useRouter } from '@tarojs/taro';
import * as announcementsApi from '@/api/announcements';
import type { AnnouncementAttachment, AnnouncementDetail } from '@/types/api';
import { API_BASE_URL, ensureFreshAccessToken } from '@/utils/request';
import { useAuthStore } from '@/stores/authStore';
import { useLoginGuard } from '@/hooks/useLoginGuard';
import dayjs from 'dayjs';

import './index.scss';

/**
 * 把富文本正文里的相对路径图片补全为绝对 URL，并附加响应式样式。
 * 管理端 WangEditor 上传正文图片后 src 形如 /api/announcement-images/xxx.png，
 * 小程序 RichText 不支持相对路径（会按本地资源加载报 500/失败），
 * 且原生 img 不限制 max-width 会溢出/裁剪，故统一处理。
 */
function resolveContentImages(html: string): string {
  return html.replace(
    /<img\b([^>]*?)(\/?)>/g,
    (m, attrs: string, selfClose: string) => {
      let next = attrs;
      // 1) 补全 src：相对路径 → 拼接 API_BASE_URL
      next = next.replace(
        /(\ssrc=["'])(\/[^"']+)(["'])/,
        (_sm, q1: string, src: string, q2: string) => {
          if (/^https?:\/\//.test(src)) return _sm;
          return `${q1}${API_BASE_URL}${src}${q2}`;
        }
      );
      // 2) 注入响应式样式：max-width:100% + height:auto，避免溢出/裁剪
      if (/\sstyle=["'][^"']*["']/.test(next)) {
        next = next.replace(
          /(\sstyle=["'])([^"']*)(["'])/,
          (_sm, q1: string, v: string, q2: string) => {
            if (/max-width/i.test(v)) return _sm;
            return `${q1}${v};max-width:100%;height:auto${q2}`;
          }
        );
      } else {
        next = `${next} style="max-width:100%;height:auto"`;
      }
      return `<img${next}${selfClose}>`;
    }
  );
}

/**
 * 通知详情页
 *
 * 路由参数：id（公告 ID）
 * 数据源：GET /api/miniapp/announcements/:id → 含正文/附件/相关推荐/收藏状态
 *
 * 布局（对齐原型）：
 * ┌──────────────────────────────────┐
 * │ < 返回        通知详情           │ ← 自定义导航栏
 * ├──────────────────────────────────┤
 * │ [置顶] 关于2025年暑假放假安排的通知  ✎│ ← 标题行
 * │ 教务处 · 2025-05-19 10:30         │
 * │ 阅读 1256                        │ ← 元信息
 * │                                  │
 * │ 各位同学：                        │
 * │ 根据学校教学安排...               │ ← 富文本正文
 * │ ...                              │
 * │                                  │
 * │                    教务处         │ ← 落款
 * │                  2025年5月19日    │
 * │                                  │
 * │ 附件                             │ ← 附件区
 * │ 📄 2025年暑假放假安排表.pdf       │
 * │    1.2MB              ↓下载      │
 * │                                  │
 * │ 相关推荐                         │ ← 相关推荐
 * │ [通] 图书馆端午节开放时间调整通知   │
 * │ [通] 关于开展2025届毕业生就业...  │
 * ├──────────────────────────────────┤
 * │ ☆收藏    ↗分享    ✓已阅          │ ← 底部操作栏
 * └──────────────────────────────────┘
 */

export default function AnnouncementDetail() {
  const router = useRouter();
  const id = Number(router.params.id);
  const { isLoggedIn } = useAuthStore();
  // 登录守卫：收藏/已阅等需登录的操作前拦截游客态（气泡提示），避免发请求再 401 报错
  const { guard } = useLoginGuard();

  const [detail, setDetail] = useState<AnnouncementDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [isFav, setIsFav] = useState(false);

  useEffect(() => {
    Taro.setNavigationBarTitle({ title: '通知详情' });

    if (!id || Number.isNaN(id)) {
      setLoading(false);
      return;
    }

    announcementsApi.getDetail(id).then((res) => {
      const d = (res as any)?.data?.announcement;
      if (d) {
        setDetail(d);
        setIsFav(d.is_favorite || false);
        // 导航栏标题改为通知名（微信原生导航栏超长自动省略号截断）；加载中/失败保持「通知详情」兜底
        if (d.title) Taro.setNavigationBarTitle({ title: d.title });
      }
    }).catch(() => {
      /* 静默失败 */
    }).finally(() => setLoading(false));
  }, [id]);

  /** 收藏 / 取消收藏（需登录：游客态提前拦截，避免发请求再 401 报错） */
  const handleFavorite = () => {
    if (!id) return;
    guard(() => {
      announcementsApi.toggleFavorite(id).then((res) => {
        setIsFav((res as any)?.data?.is_favorite || false);
        Taro.showToast({ title: isFav ? '已取消收藏' : '已收藏', icon: 'none' });
      });
    });
  };

  /** 分享 */
  const handleShare = () => {
    Taro.showToast({ title: '等待学校开放接口', icon: 'none' });
  };

  /** 标记已读（需登录：游客态提前拦截） */
  const handleMarkRead = () => {
    if (!id || detail?.is_read) return;
    guard(() => {
      announcementsApi.markRead(id).then(() => {
        if (detail) setDetail({ ...detail, is_read: true });
        Taro.showToast({ title: '已标记已阅', icon: 'none' });
      });
    });
  };

  /** 跳转相关推荐 */
  const goToRelated = (relatedId: number) => {
    Taro.redirectTo({ url: `/pages/announcement/detail/index?id=${relatedId}` });
  };

  /**
   * 下载附件
   *
   * 必须走后端带鉴权的下载接口（att.download_url，形如 /api/miniapp/announcements/attachment/<id>），
   * 而不是 att.file_url（那是磁盘相对路径，无法直接下载，且直连会绕过可见性鉴权）。
   * downloadFile 需带 token（该接口是 @student_bound_required），并做登录预刷新防过期。
   */
  const downloadAttachment = async (att: AnnouncementAttachment) => {
    // 优先用后端给的鉴权下载接口；拿不到时兜底文件路径（拼成完整 URL）
    const path = att.download_url || att.file_url;
    if (!path) {
      Taro.showToast({ title: '附件地址缺失', icon: 'none' });
      return;
    }
    const full = /^https?:\/\//.test(path) ? path : `${API_BASE_URL}${path}`;

    // downloadFile 不走 request 封装，需手动补 token 刷新（同反馈图片上传的处理）
    const token = await ensureFreshAccessToken();
    Taro.showLoading({ title: '下载中…' });
    Taro.downloadFile({
      url: full,
      header: token ? { Authorization: `Bearer ${token}` } : {},
      success: (res) => {
        if (res.statusCode === 200 && res.tempFilePath) {
          Taro.openDocument({ filePath: res.tempFilePath, showMenu: true });
        } else if (res.statusCode === 401) {
          Taro.showToast({ title: '登录已过期，请重新登录', icon: 'none' });
        } else if (res.statusCode === 404) {
          Taro.showToast({ title: '附件不存在或已删除', icon: 'none' });
        } else {
          Taro.showToast({ title: '下载失败', icon: 'none' });
        }
      },
      fail: (err) => {
        const msg = (err as { errMsg?: string })?.errMsg || '';
        // downloadFile 域名白名单是独立的，报 domain list 时给出明确提示
        if (/url not in domain list/i.test(msg)) {
          Taro.showToast({
            title: '下载域名未加入白名单，请在微信后台配置 downloadFile 合法域名',
            icon: 'none',
            duration: 3000,
          });
        } else {
          Taro.showToast({ title: '下载失败', icon: 'none' });
        }
      },
      complete: () => Taro.hideLoading(),
    });
  };

  if (!id || Number.isNaN(id)) {
    return (
      <View className="detail-page">
        <View className="detail-error">
          <Text>缺少公告 ID 参数</Text>
        </View>
      </View>
    );
  }

  return (
    <View className="detail-page">

      {loading ? (
        <View className="detail-loading">
          <View className="detail-spinner" />
        </View>
      ) : !detail ? (
        <View className="detail-error">
          <Text>通知不存在或已撤回</Text>
        </View>
      ) : (
        <>
          <ScrollView className="detail-scroll" scrollY enhanced showScrollbar={false}>
            {/* 标题区 */}
            <View className="detail-header">
              {/* 第一行：置顶标签 + 标题 + 编辑图标 */}
              <View className="detail-title-row">
                {detail.is_top && <Text className="detail-top-tag">置顶</Text>}
                <Text className="detail-title">{detail.title}</Text>
                <View className="detail-edit-icon">
                  <Text className="iconfont icon-bianji1" />
                </View>
              </View>
              {/* 第二行：部门 · 时间 */}
              <View className="detail-meta-row">
                {detail.department && (
                  <Text className="meta-dept">{detail.department}</Text>
                )}
                {detail.published_label && (
                  <>
                    <Text className="meta-sep"> · </Text>
                    <Text className="meta-time">{detail.published_label}</Text>
                  </>
                )}
              </View>
              {/* 第三行：阅读数（独立行，带边框） */}
              {(detail.view_count > 0) && (
                <View className="detail-views-row">
                  <Text className="meta-views">阅读 {detail.view_count}</Text>
                </View>
              )}
            </View>

            {/* 封面图：标题与正文之间，有图才显示（无图不占位） */}
            {detail.cover_url ? (
              <Image
                className="detail-cover"
                src={`${API_BASE_URL}${detail.cover_url}`}
                mode="widthFix"
              />
            ) : null}

            {/* 正文（相对路径图片已补全为绝对 URL） */}
            <View className="detail-body">
              {detail.content ? (
                <RichText nodes={resolveContentImages(detail.content)} />
              ) : (
                <Text className="body-empty">暂无内容</Text>
              )}
            </View>

            {/* 落款（右对齐，两行） */}
            <View className="detail-signature">
              {detail.department && (
                <Text className="sign-dept">{detail.department}</Text>
              )}
              {detail.published_at && (
                <Text className="sign-date">
                  {dayjs(detail.published_at).format('YYYY年M月D日')}
                </Text>
              )}
            </View>

            {/* 附件 */}
            {detail.attachments && detail.attachments.length > 0 && (
              <View className="detail-section">
                <Text className="section-title">附件</Text>
                <View className="attach-list">
                  {detail.attachments.map((att) => (
                    <View
                      key={att.id}
                      className="attach-item"
                      onClick={() => guard(() => downloadAttachment(att))}
                    >
                      <View className="attach-icon">
                        <Text className="iconfont icon-RectangleCopy1 attach-file-icon" />
                      </View>
                      <View className="attach-info">
                        <Text className="attach-name">{att.file_name}</Text>
                        <Text className="attach-size">{att.file_size_label}</Text>
                      </View>
                      <View className="attach-download">
                        <Text className="iconfont icon-xiazai" />
                      </View>
                    </View>
                  ))}
                </View>
              </View>
            )}

            {/* 相关推荐 */}
            {detail.related && detail.related.length > 0 && (
              <View className="detail-section">
                <Text className="section-title">相关推荐</Text>
                <View className="related-list">
                  {detail.related.map((item) => (
                    <View
                      key={item.id}
                      className="related-item"
                      onClick={() => goToRelated(item.id)}
                    >
                      <Text className={`related-tag ${item.category === 'urgent' ? 'tag-urgent' : item.category === 'activity' ? 'tag-activity' : ''}`}>
                        {(detail.category_label || item.category || '').charAt(0)}
                      </Text>
                      <View className="related-body">
                        <Text className="related-title">{item.title}</Text>
                        <Text className="related-meta">
                          {detail.department || ''}
                          {item.published_label && ` · ${item.published_label}`}
                        </Text>
                      </View>
                    </View>
                  ))}
                </View>
              </View>
            )}

            {/* 底部灰色隔断区：操作栏为 fixed（约 100rpx + 安全区），留白需明显高于栏高；
                灰底与「正文/相关推荐」之间的隔断同色，拉到底形成完整灰色隔断 */}
            <View className="detail-bottom-gap" />
          </ScrollView>

          {/* 底部操作栏 */}
          <View className="detail-actions">
            <View className={`action-btn ${isFav ? 'action-active' : ''}`} onClick={handleFavorite}>
              <Text className="iconfont icon-a-rongqi2231x action-icon action-star" />
              <Text className="action-text">收藏</Text>
            </View>
            <View className="action-btn" onClick={handleShare}>
              <Text className="action-icon iconfont icon-fenxiang" />
              <Text className="action-text">分享</Text>
            </View>
            <View className={`action-btn ${detail.is_read ? 'action-active' : ''}`} onClick={handleMarkRead}>
              <Text className="action-icon iconfont icon-yiyuedu" />
              <Text className="action-text">已阅</Text>
            </View>
          </View>
        </>
      )}
    </View>
  );
}
