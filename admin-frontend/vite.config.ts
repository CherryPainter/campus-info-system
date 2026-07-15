import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // 配置路径别名，使用 @ 指向 src 目录
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    // 生产构建优化
    minify: 'terser',
    terserOptions: {
      compress: {
        drop_console: true,
        drop_debugger: true,
      },
    },
    rollupOptions: {
      output: {
        // 代码分割，分离第三方库
        manualChunks(id: string) {
          if (id.includes('node_modules/react') || id.includes('node_modules/react-dom') || id.includes('node_modules/react-router')) {
            return 'vendor-react';
          }
          if (id.includes('node_modules/antd') || id.includes('node_modules/@ant-design')) {
            return 'vendor-antd';
          }
        },
      },
    },
    // 启用 gzip 压缩报告
    reportCompressedSize: true,
    // chunk 大小警告阈值
    chunkSizeWarningLimit: 1000,
  },
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: ['localhost', '127.0.0.1'],
    proxy: {
      // 代理后端 API 请求到 Flask 服务（本地开发）
      '/api': {
        target: 'http://localhost:29528',
        changeOrigin: true,
      },
    },
  },
})
