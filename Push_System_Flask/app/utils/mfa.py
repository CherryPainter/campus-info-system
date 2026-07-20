#!/usr/bin/env python3
"""
多因素认证 (MFA) 工具模块
支持 TOTP (Time-based One-Time Password) 基于时间的一次性密码

使用 Google Authenticator 或类似应用扫描 QR 码即可
"""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from app.core.logger import get_logger

logger = get_logger(__name__)


class TOTP:
    """
    TOTP (Time-based One-Time Password) 实现

    符合 RFC 6238 标准，与 Google Authenticator 兼容
    """

    def __init__(self, secret: str, digits: int = 6, interval: int = 30):
        """
        初始化 TOTP

        Args:
            secret: Base32 编码的密钥
            digits: OTP 位数，默认 6
            interval: 时间窗口（秒），默认 30
        """
        self.secret = secret
        self.digits = digits
        self.interval = interval

    def generate(self, timestamp: int | None = None) -> str:
        """
        生成当前时间窗口的 OTP

        Args:
            timestamp: 指定时间戳，默认当前时间

        Returns:
            str: 6位数字 OTP
        """
        if timestamp is None:
            timestamp = int(time.time())

        # 计算时间窗口计数器
        counter = timestamp // self.interval

        # 解码密钥
        key = base64.b32decode(self.secret.upper() + "=" * ((8 - len(self.secret) % 8) % 8))

        # 将计数器转为 8 字节大端序
        counter_bytes = struct.pack(">Q", counter)

        # HMAC-SHA1
        mac = hmac.new(key, counter_bytes, hashlib.sha1).digest()

        # 动态截断
        offset = mac[-1] & 0x0F
        code = struct.unpack(">I", mac[offset : offset + 4])[0] & 0x7FFFFFFF

        # 取模得到指定位数
        otp = code % (10**self.digits)

        return str(otp).zfill(self.digits)

    def verify(self, otp: str, window: int = 1) -> bool:
        """
        验证 OTP

        Args:
            otp: 用户输入的 OTP
            window: 时间窗口容错范围（前后几个窗口），默认 1

        Returns:
            bool: 验证是否通过
        """
        timestamp = int(time.time())

        # 检查当前窗口及前后窗口
        for i in range(-window, window + 1):
            if self.generate(timestamp + i * self.interval) == otp:
                return True

        return False

    def get_provisioning_uri(self, account_name: str, issuer: str = "CampusNotify") -> str:
        """
        生成用于二维码的 URI

        Args:
            account_name: 账户名（如 admin）
            issuer: 发行者名称（使用英文避免兼容性问题）

        Returns:
            str: otpauth URI
        """
        # 使用简短的 issuer，避免二维码过于密集
        # 只对 account_name 和 issuer 中的特殊字符进行编码，保留冒号和空格原样

        label = f"{issuer}:{account_name}"

        # 只包含必需的参数，避免二维码过于密集
        return (
            f"otpauth://totp/{quote(label, safe=':@/')}?"
            f"secret={self.secret}&"
            f"issuer={quote(issuer)}"
        )


class MFAManager:
    """
    MFA 管理器

    管理用户的 MFA 配置和验证
    """

    @staticmethod
    def generate_secret() -> str:
        """生成新的 MFA 密钥"""
        return base64.b32encode(secrets.token_bytes(20)).decode("utf-8").rstrip("=")

    @staticmethod
    def setup_mfa(user_id: str) -> dict:
        """
        为用户设置 MFA

        Returns:
            dict: 包含 secret 和 provisioning_uri
        """
        secret = MFAManager.generate_secret()
        totp = TOTP(secret)

        uri = totp.get_provisioning_uri(user_id)

        logger.info(f"为用户 {user_id} 生成 MFA 配置")

        return {
            "secret": secret,
            "provisioning_uri": uri,
        }

    @staticmethod
    def verify_mfa(secret: str, otp: str) -> bool:
        """
        验证 MFA 代码

        Args:
            secret: MFA 密钥
            otp: 用户输入的 6 位代码

        Returns:
            bool: 验证是否通过
        """
        if not secret or not otp:
            return False

        totp = TOTP(secret)
        return totp.verify(otp)


# 全局 MFA 管理器实例
mfa_manager = MFAManager()
