/**
 * 公共 Footer 组件
 * 包含用户协议、网站介绍、联系我们、隐私政策、法律声明、Cookies政策及版权信息
 */
import React from 'react';
import { APP_VERSION } from '@/version';

interface FooterLink {
  href: string;
  label: string;
}

interface FooterProps {
  style?: React.CSSProperties;
}

/**
 * 链接列表配置
 */
const footerLinks: FooterLink[] = [
  { href: '/terms', label: '用户协议' },
  { href: '/about', label: '网站介绍' },
  { href: '/contact', label: '联系我们' },
  { href: '/privacy', label: '隐私政策' },
  { href: '/legal', label: '法律声明' },
  { href: '/cookies', label: 'Cookies政策' },
];

/**
 * 公共 Footer 组件
 * 用于管理后台和登录页面
 */
export default function Footer({ style }: FooterProps) {
  // 备案信息从环境变量读取（部署时在 .env.local 配置，源码不含真实值）
  const beianIcp = import.meta.env.VITE_BEIAN_ICP;
  const beianMps = import.meta.env.VITE_BEIAN_MPS;

  return (
    <footer
      style={{
        textAlign: 'center',
        backgroundColor: 'rgba(250, 250, 250, 0.95)',
        padding: '16px 0',
        borderTop: '1px solid #f0f0f0',
        ...style,
      }}
    >
      {/* 链接行 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: 16,
          flexWrap: 'wrap',
          marginBottom: 8,
        }}
      >
        {footerLinks.map((link, index) => (
          <React.Fragment key={link.href}>
            <a
              href={link.href}
              style={{
                fontSize: 13,
                color: '#666',
                textDecoration: 'none',
              }}
              target="_blank"
              rel="noopener noreferrer"
            >
              {link.label}
            </a>
            {index < footerLinks.length - 1 && (
              <span style={{ fontSize: 12, color: '#d9d9d9' }}>|</span>
            )}
          </React.Fragment>
        ))}
      </div>

      {/* 版本和技术支持信息 */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          gap: 16,
          flexWrap: 'wrap',
          marginBottom: 8,
        }}
      >
        <span style={{ fontSize: 12, color: '#999' }}>
          校园信息聚合与智能推送系统 v{APP_VERSION}
        </span>
        <span style={{ fontSize: 12, color: '#d9d9d9' }}>|</span>
        <span style={{ fontSize: 12, color: '#999' }}>
          技术支持：CherryPainter
        </span>
        <span style={{ fontSize: 12, color: '#d9d9d9' }}>|</span>
        <span style={{ fontSize: 12, color: '#999' }}>
          © 2026 CherryPainter. All rights reserved.
        </span>
      </div>

      {/* 备案信息（从环境变量读取，未配置则不渲染） */}
      {(beianIcp || beianMps) && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            gap: 16,
            flexWrap: 'wrap',
          }}
        >
          {beianIcp && (
            <a
              href="https://beian.miit.gov.cn"
              style={{
                fontSize: 12,
                color: '#999',
                textDecoration: 'none',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                transition: 'all 0.3s ease',
              }}
              onMouseEnter={(e) => {
                const target = e.currentTarget;
                target.style.color = '#1890ff';
                target.style.textDecoration = 'underline';
              }}
              onMouseLeave={(e) => {
                const target = e.currentTarget;
                target.style.color = '#999';
                target.style.textDecoration = 'none';
              }}
              target="_blank"
              rel="noopener noreferrer"
            >
              {beianIcp}
            </a>
          )}
          {beianIcp && beianMps && (
            <span style={{ fontSize: 12, color: '#d9d9d9' }}>|</span>
          )}
          {beianMps && (
            <a
              href="https://beian.mps.gov.cn/"
              style={{
                fontSize: 12,
                color: '#999',
                textDecoration: 'none',
                display: 'flex',
                alignItems: 'center',
                gap: 4,
                transition: 'all 0.3s ease',
              }}
              onMouseEnter={(e) => {
                const target = e.currentTarget;
                target.style.color = '#1890ff';
                target.style.textDecoration = 'underline';
              }}
              onMouseLeave={(e) => {
                const target = e.currentTarget;
                target.style.color = '#999';
                target.style.textDecoration = 'none';
              }}
              target="_blank"
              rel="noopener noreferrer"
            >
              <img
                src="/gongan-badge.png"
                alt="公安备案徽标"
                style={{
                  width: 16,
                  height: 16,
                  verticalAlign: 'middle',
                }}
              />
              {beianMps}
            </a>
          )}
        </div>
      )}

    </footer>
  );
}
