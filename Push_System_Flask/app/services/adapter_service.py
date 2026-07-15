#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推送适配器服务 - 支持多 Webhook"""
import os
import json
import requests
from app.core.logger import get_logger

# 使用统一日志系统
logger = get_logger(__name__)


class BaseAdapter:
    """适配器基类"""
    
    def __init__(self, config=None):
        self.config = config or {}
        self.status = 'initialized'
    
    def init(self):
        self.status = 'ready'
        return True
    
    def send(self, message):
        raise NotImplementedError
    
    def send_image(self, image_path):
        raise NotImplementedError
    
    def get_status(self):
        return {'name': self.__class__.__name__, 'status': self.status}


class WeComAdapter(BaseAdapter):
    """企业微信适配器 - 支持单个 webhook"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.webhook_url = config.get('webhook_url') if config else None
        self.name = config.get('name', 'wecom') if config else 'wecom'
    
    def init(self):
        if not self.webhook_url:
            self.status = 'error'
            return False
        return super().init()
    
    def send(self, message):
        try:
            resp = requests.post(self.webhook_url, json=message, timeout=10)
            data = resp.json()
            if data.get('errcode') == 0:
                self.status = 'ok'
                return {'success': True, 'data': data}
            else:
                self.status = 'error'
                return {'success': False, 'error': data.get('errmsg', 'Unknown error'), 'data': data}
        except Exception as e:
            self.status = 'error'
            return {'success': False, 'error': str(e)}
    
    def send_image(self, image_path):
        """发送图片：使用 base64 + md5 方式（企业微信群机器人推荐方式）"""
        if not os.path.exists(image_path):
            logger.error(f'send_image: 图片文件不存在: {image_path}')
            return {'success': False, 'error': 'Image file not found'}
        
        try:
            import base64
            import hashlib
            
            with open(image_path, 'rb') as f:
                file_data = f.read()
            
            b64 = base64.b64encode(file_data).decode('utf-8')
            md5 = hashlib.md5(file_data).hexdigest()
            
            file_size = os.path.getsize(image_path)
            logger.info(f'send_image: 发送图片 {os.path.basename(image_path)} ({file_size / 1024:.1f}KB, base64长度: {len(b64)})')
            
            result = self.send({
                'msgtype': 'image',
                'image': {
                    'base64': b64,
                    'md5': md5
                }
            })
            
            if not result.get('success'):
                logger.error(f'send_image: 发送图片消息失败: {result}')
            return result
        except Exception as e:
            logger.error(f'send_image: 发送图片异常: {e}')
            return {'success': False, 'error': str(e)}
    
    def _upload_media(self, image_path):
        """上传图片到企业微信"""
        try:
            from urllib.parse import urlparse
            
            parsed = urlparse(self.webhook_url)
            key = parsed.query.split('key=')[-1] if 'key=' in parsed.query else ''
            if not key:
                logger.error('_upload_media: 无法从 webhook URL 提取 key')
                return None
            
            # 通过文件头检测真实 MIME 类型
            mime_type = self._detect_mime_type(image_path)
            logger.info(f'_upload_media: 检测到 MIME 类型: {mime_type}')
            
            upload_url = f'https://qyapi.weixin.qq.com/cgi-bin/webhook/upload_media?key={key}&type=image'
            file_size = os.path.getsize(image_path)
            logger.info(f'_upload_media: 上传图片 {os.path.basename(image_path)} ({file_size / 1024:.1f}KB, {mime_type})')
            
            with open(image_path, 'rb') as f:
                # 使用英文文件名避免中文编码问题
                safe_filename = 'image.png' if mime_type == 'image/png' else 'image.jpg'
                
                # 构建 multipart/form-data 请求体（企业微信要求的格式）
                import uuid
                boundary = f'----WebKitFormBoundary{uuid.uuid4().hex[:16]}'
                
                file_data = f.read()
                body = (
                    f'------{boundary}\r\n'
                    f'Content-Disposition: form-data; name="media"; filename="{safe_filename}"\r\n'
                    f'Content-Type: {mime_type}\r\n\r\n'
                ).encode('utf-8') + file_data + f'\r\n------{boundary}--\r\n'.encode('utf-8')
                
                headers = {
                    'Content-Type': f'multipart/form-data; boundary=----{boundary}',
                }
                resp = requests.post(upload_url, data=body, headers=headers, timeout=30)
            data = resp.json()
            if data.get('errcode') == 0:
                logger.info(f'_upload_media: 上传成功, media_id={data.get("media_id")}')
                return data.get('media_id')
            else:
                logger.error(f'_upload_media: 上传失败, response={data}')
                return None
        except Exception as e:
            logger.error(f'_upload_media: 上传异常: {e}')
            return None
    
    def _detect_mime_type(self, image_path):
        """通过文件头检测真实 MIME 类型"""
        try:
            with open(image_path, 'rb') as f:
                header = f.read(16)
            
            # PNG: 89 50 4E 47
            if header.startswith(b'\x89PNG\r\n\x1a\n'):
                return 'image/png'
            # JPEG: FF D8 FF
            if header.startswith(b'\xff\xd8\xff'):
                return 'image/jpeg'
            # GIF: GIF87a 或 GIF89a
            if header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
                return 'image/gif'
            # BMP: BM
            if header.startswith(b'BM'):
                return 'image/bmp'
            # WebP: RIFF....WEBP
            if header.startswith(b'RIFF') and b'WEBP' in header[:12]:
                return 'image/webp'
            
            # 默认
            return 'image/png'
        except Exception:
            return 'image/png'


class MultiWeComAdapter(BaseAdapter):
    """多企业微信适配器 - 同时推送到多个 webhook"""
    
    def __init__(self, config=None):
        super().__init__(config)
        self.adapters = []
        self.name = config.get('name', 'multi_wecom') if config else 'multi_wecom'
        
        # 从配置中创建多个子适配器（先去重）
        webhook_urls = config.get('webhook_urls', []) if config else []
        # 使用字典去重，保持顺序
        seen_urls = {}
        unique_urls = []
        for url in webhook_urls:
            if url and url not in seen_urls:
                seen_urls[url] = True
                unique_urls.append(url)
        
        if len(unique_urls) != len(webhook_urls):
            logger.warning(f'Webhook URL 去重: 从 {len(webhook_urls)} 个减少到 {len(unique_urls)} 个')
        
        for i, url in enumerate(unique_urls):
            adapter = WeComAdapter({
                'webhook_url': url,
                'name': f'{self.name}_{i}'
            })
            self.adapters.append(adapter)
    
    def init(self):
        if not self.adapters:
            self.status = 'error'
            return False
        
        success_count = sum(1 for adapter in self.adapters if adapter.init())
        if success_count == 0:
            self.status = 'error'
            return False
        
        self.status = 'ready'
        logger.info(f'多 Webhook 适配器初始化完成: {success_count}/{len(self.adapters)} 个成功')
        return True
    
    def send(self, message):
        """推送到所有配置的 webhook"""
        results = []
        success_count = 0
        
        for adapter in self.adapters:
            result = adapter.send(message)
            results.append({
                'adapter': adapter.name,
                'success': result.get('success'),
                'error': result.get('error')
            })
            if result.get('success'):
                success_count += 1
        
        # 只要有至少一个成功，就认为整体成功
        overall_success = success_count > 0
        if overall_success:
            self.status = 'ok'
        else:
            self.status = 'error'
        
        return {
            'success': overall_success,
            'success_count': success_count,
            'total_count': len(self.adapters),
            'results': results
        }
    
    def send_image(self, image_path):
        """发送图片到所有 webhook"""
        results = []
        success_count = 0
        
        for adapter in self.adapters:
            result = adapter.send_image(image_path)
            results.append({
                'adapter': adapter.name,
                'success': result.get('success'),
                'error': result.get('error')
            })
            if result.get('success'):
                success_count += 1
        
        overall_success = success_count > 0
        return {
            'success': overall_success,
            'success_count': success_count,
            'total_count': len(self.adapters),
            'results': results
        }
    
    def get_status(self):
        return {
            'name': self.__class__.__name__,
            'status': self.status,
            'adapter_count': len(self.adapters),
            'adapters': [adapter.get_status() for adapter in self.adapters]
        }


class AdapterService:
    """适配器管理服务 - 支持动态加载数据库 webhook"""
    
    def __init__(self):
        self._adapters = {}
        self._app = None
    
    def init_app(self, app):
        self._app = app
        
        # 优先从数据库加载 webhook
        self._load_webhooks_from_db()
        
        # 如果数据库没有配置，回退到 .env 配置
        if 'wecom' not in self._adapters:
            self._load_webhooks_from_env()
        
        logger.info(f'适配器服务初始化完成，已注册: {list(self._adapters.keys())}')
    
    def _load_webhooks_from_db(self):
        """从数据库加载 webhook 配置（按模块分组）"""
        try:
            from app.core.database import get_db
            from app.model.webhook import Webhook
            
            session = get_db()
            try:
                # 按模块加载 webhook
                modules = ['course', 'weather', 'electricity', 'system']
                
                for module in modules:
                    webhooks = Webhook.get_webhooks_by_module(session, module)
                    if webhooks:
                        # 去重：使用 set 去除重复的 URL
                        urls = list({w.url for w in webhooks})
                        if len(urls) == 1:
                            adapter = WeComAdapter({'webhook_url': urls[0], 'name': module})
                        else:
                            adapter = MultiWeComAdapter({'webhook_urls': urls, 'name': module})
                        adapter.init()
                        self._adapters[module] = adapter
                        logger.info(f'从数据库加载 {module} 适配器: {len(urls)} 个 webhook (去重后)')
                
                # 如果没有加载到任何配置，回退到 .env
                if not self._adapters:
                    self._load_webhooks_from_env()
                    
            finally:
                session.close()
        except Exception as e:
            logger.warning(f'从数据库加载 webhook 失败: {e}，将使用 .env 配置')
    
    def _load_webhooks_from_env(self):
        """从环境变量加载 webhook 配置（回退方案）"""
        from app.core.config import Config
        
        # 初始化主推送适配器（去重）
        webhook_urls = Config.get_wecom_webhooks()
        if webhook_urls:
            # 去重
            seen_urls = {}
            unique_urls = []
            for url in webhook_urls:
                if url and url not in seen_urls:
                    seen_urls[url] = True
                    unique_urls.append(url)
            
            if len(unique_urls) != len(webhook_urls):
                logger.warning(f'Webhook URL 去重 (env): 从 {len(webhook_urls)} 个减少到 {len(unique_urls)} 个')
            
            if len(unique_urls) == 1:
                adapter = WeComAdapter({'webhook_url': unique_urls[0], 'name': 'wecom'})
            else:
                adapter = MultiWeComAdapter({'webhook_urls': unique_urls, 'name': 'wecom'})
            adapter.init()
            self._adapters['wecom'] = adapter
            logger.info(f'从 .env 加载推送适配器: {len(unique_urls)} 个 webhook')
        
        # 初始化状态告警适配器（去重）
        status_urls = Config.get_status_webhooks()
        if status_urls:
            # 去重
            seen_urls = {}
            unique_urls = []
            for url in status_urls:
                if url and url not in seen_urls:
                    seen_urls[url] = True
                    unique_urls.append(url)
            
            if len(unique_urls) != len(status_urls):
                logger.warning(f'状态 Webhook URL 去重 (env): 从 {len(status_urls)} 个减少到 {len(unique_urls)} 个')
            
            if len(unique_urls) == 1:
                adapter = WeComAdapter({'webhook_url': unique_urls[0], 'name': 'status'})
            else:
                adapter = MultiWeComAdapter({'webhook_urls': unique_urls, 'name': 'status'})
            adapter.init()
            self._adapters['status'] = adapter
            logger.info(f'从 .env 加载状态适配器: {len(unique_urls)} 个 webhook')
    
    def reload_webhooks(self):
        """重新加载 webhook 配置（热重载）"""
        logger.info('正在重载 webhook 配置...')
        
        # 清空现有适配器
        self._adapters.clear()
        
        # 重新加载
        self._load_webhooks_from_db()
        
        # 如果数据库为空，回退到 .env
        if not self._adapters:
            self._load_webhooks_from_env()
        
        logger.info(f'Webhook 配置重载完成: {list(self._adapters.keys())}')
    
    def get_adapter(self, name='wecom'):
        return self._adapters.get(name)
    
    def get_all_status(self):
        return {name: adapter.get_status() for name, adapter in self._adapters.items()}
    
    def send_to_all(self, message, adapter_names=None):
        """
        发送消息到指定的适配器
        
        Args:
            message: 消息内容
            adapter_names: 适配器名称列表，默认 ['wecom']
        
        Returns:
            dict: 各适配器的推送结果
        """
        if adapter_names is None:
            adapter_names = ['wecom']
        
        results = {}
        for name in adapter_names:
            adapter = self._adapters.get(name)
            if adapter:
                results[name] = adapter.send(message)
            else:
                results[name] = {'success': False, 'error': 'Adapter not found'}
        
        return results


# 全局单例
adapter_service = AdapterService()
