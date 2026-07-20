#!/usr/bin/env python3
"""
文件上传安全模块

提供文件上传的安全防护功能：
- 文件大小限制
- 文件类型验证（MIME类型和文件扩展名）
- 文件名验证（防止路径遍历）
- 文件内容验证（Magic Bytes检查）

使用方法：
    from app.utils.file_upload_security import validate_file_upload, FileUploadError

    try:
        validated_file = validate_file_upload(request.files['file'], allowed_types=['image/jpeg', 'image/png'])
        # 处理验证通过的文件
    except FileUploadError as e:
        return jsonify({'status': 'error', 'message': str(e)}), 400
"""

import base64
import hashlib
import os
import re

try:
    import magic
except ImportError:
    # python-magic 未安装时降级：仅影响 validate_file_type 的 Magic Bytes 探测，
    # 会自动回退到扩展名检查；头像校验（validate_avatar_data_uri）不依赖 magic，照常可用。
    magic = None
from app.core.logger import get_logger

logger = get_logger(__name__)


class FileUploadError(Exception):
    """文件上传错误"""

    pass


# 默认允许的文件类型（MIME类型）
DEFAULT_ALLOWED_TYPES = {
    "image/jpeg": ".jpg,.jpeg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}

# 默认最大文件大小（5MB）
DEFAULT_MAX_FILE_SIZE = 5 * 1024 * 1024

# 允许的图片文件类型
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp"}
MAX_IMAGE_SIZE = 2 * 1024 * 1024  # 2MB

# 头像 data URI 允许的 MIME 及其文件头签名（用于 Magic Bytes 校验，防伪造/防 SVG XSS）
_ALLOWED_AVATAR_MIME = {
    "image/jpeg": b"\xff\xd8\xff",
    "image/png": b"\x89PNG\r\n\x1a\n",
    "image/gif": b"GIF8",
    "image/webp": b"RIFF",  # WEBP 实际为 RIFF....WEBP
}
# 头像最大解码后体积
AVATAR_MAX_SIZE = 2 * 1024 * 1024  # 2MB
# 头像修改频率限制：一年内最多修改次数
AVATAR_QUOTA = 3
AVATAR_QUOTA_DAYS = 365


def validate_filename(filename):
    """
    验证文件名（防止路径遍历攻击）

    Args:
        filename: 原始文件名

    Returns:
        安全的文件名

    Raises:
        FileUploadError: 文件名不安全
    """
    if not filename:
        raise FileUploadError("文件名不能为空")

    # 移除路径分隔符（防止路径遍历）
    filename = os.path.basename(filename)

    # 检查是否包含路径遍历字符
    if ".." in filename or "/" in filename or "\\" in filename:
        raise FileUploadError("文件名包含非法字符")

    # 检查文件名长度
    if len(filename) > 255:
        raise FileUploadError("文件名过长")

    # 检查文件扩展名
    _, ext = os.path.splitext(filename)
    if not ext:
        raise FileUploadError("文件必须有扩展名")

    return filename


def validate_file_size(file, max_size=None):
    """
    验证文件大小

    Args:
        file: 文件对象（FileStorage）
        max_size: 最大文件大小（字节），默认5MB

    Raises:
        FileUploadError: 文件过大
    """
    if max_size is None:
        max_size = DEFAULT_MAX_FILE_SIZE

    # 获取文件大小
    file.seek(0, 2)  # 移动到文件末尾
    file_size = file.tell()
    file.seek(0)  # 重置文件指针

    if file_size > max_size:
        max_size_mb = max_size / (1024 * 1024)
        raise FileUploadError(f"文件大小不能超过 {max_size_mb:.1f}MB")


def validate_file_type(file, allowed_types=None):
    """
    验证文件类型（MIME类型）

    Args:
        file: 文件对象（FileStorage）
        allowed_types: 允许的MIME类型集合，默认允许图片类型

    Returns:
        检测到的MIME类型

    Raises:
        FileUploadError: 文件类型不允许
    """
    if allowed_types is None:
        allowed_types = DEFAULT_ALLOWED_TYPES

    # 使用 python-magic 检查文件内容（Magic Bytes）；未安装则回退扩展名检查
    mime_type = None
    if magic is not None:
        try:
            m = magic.Magic(mime=True)
            file.seek(0)
            mime_type = m.from_buffer(file.read(1024))
            file.seek(0)
        except Exception as e:
            logger.warning(f"Magic Bytes检查失败: {e}")

    if mime_type is None:
        # 回退到文件扩展名检查
        _, ext = os.path.splitext(file.filename or "")
        ext = ext.lower()
        for allowed_mime, extensions in DEFAULT_ALLOWED_TYPES.items():
            if ext in extensions.split(","):
                mime_type = allowed_mime
                break
        else:
            raise FileUploadError("无法检测文件类型")

    # 检查MIME类型是否允许
    if mime_type not in allowed_types:
        raise FileUploadError(f"不支持的文件类型: {mime_type}")

    return mime_type


def validate_file_content(file, mime_type):
    """
    验证文件内容（防止伪造文件类型）

    Args:
        file: 文件对象（FileStorage）
        mime_type: 检测到的MIME类型

    Raises:
        FileUploadError: 文件内容不安全
    """
    # 对于图片文件，尝试用PIL打开验证
    if mime_type.startswith("image/"):
        try:
            from PIL import Image

            file.seek(0)
            img = Image.open(file)
            img.verify()  # 验证图片完整性
            file.seek(0)
        except Exception as e:
            raise FileUploadError(f"图片文件损坏或格式不正确: {e}")

    # 对于PDF文件，检查PDF头
    if mime_type == "application/pdf":
        file.seek(0)
        header = file.read(4)
        file.seek(0)
        if header != b"%PDF":
            raise FileUploadError("PDF文件格式不正确")


def generate_secure_filename(file, original_filename):
    """
    生成安全的文件名（使用哈希值）

    Args:
        file: 文件对象
        original_filename: 原始文件名

    Returns:
        安全的文件名（哈希值 + 扩展名）
    """
    # 计算文件哈希值
    file.seek(0)
    file_hash = hashlib.sha256(file.read()).hexdigest()
    file.seek(0)

    # 获取文件扩展名
    _, ext = os.path.splitext(original_filename)

    # 生成安全的文件名
    return f"{file_hash}{ext}"


def validate_file_upload(file, allowed_types=None, max_size=None, check_content=True):
    """
    验证文件上传

    Args:
        file: 文件对象（FileStorage）
        allowed_types: 允许的MIME类型集合
        max_size: 最大文件大小（字节）
        check_content: 是否检查文件内容

    Returns:
        验证通过的文件对象

    Raises:
        FileUploadError: 文件验证失败
    """
    if not file or not file.filename:
        raise FileUploadError("未选择文件")

    # 1. 验证文件名
    filename = validate_filename(file.filename)

    # 2. 验证文件大小
    validate_file_size(file, max_size)

    # 3. 验证文件类型
    mime_type = validate_file_type(file, allowed_types)

    # 4. 验证文件内容（可选）
    if check_content:
        validate_file_content(file, mime_type)

    # 5. 生成安全的文件名
    secure_filename = generate_secure_filename(file, filename)

    logger.info(f"[文件上传] 文件验证通过: {filename} -> {secure_filename}, MIME: {mime_type}")

    return file


def validate_avatar_data_uri(raw, max_size=AVATAR_MAX_SIZE):
    """
    校验头像 Base64 Data URI（前端上传头像用的是 data:image/...;base64,... 形式）。

    防护点：
    - 仅允许 JPG / PNG / GIF / WEBP，显式拒绝 SVG（SVG 可内嵌 <script> 造成存储型 XSS）。
    - 解码后校验文件头 Magic Bytes，防止“改后缀/改 MIME”伪造。
    - 限制解码后体积，防止超大 payload 撑爆存储/内存（DoS）。

    Args:
        raw: 原始头像字符串（data URI）
        max_size: 解码后最大字节数

    Returns:
        校验通过的 data URI（原样返回）

    Raises:
        FileUploadError: 校验不通过
    """
    if not raw or not isinstance(raw, str):
        raise FileUploadError("头像数据为空")
    m = re.match(r"^data:([^;]+);base64,(.+)$", raw, re.DOTALL)
    if not m:
        raise FileUploadError("头像格式必须是 data:image/...;base64,...")
    mime = m.group(1).lower().strip()
    if mime not in _ALLOWED_AVATAR_MIME:
        raise FileUploadError("仅支持 JPG / PNG / GIF / WEBP 格式头像")
    b64 = re.sub(r"\s+", "", m.group(2))
    try:
        raw_bytes = base64.b64decode(b64, validate=True)
    except Exception:
        raise FileUploadError("头像数据不是合法的 Base64 编码")
    if len(raw_bytes) < 16:
        raise FileUploadError("头像内容过小或已损坏")
    if len(raw_bytes) > max_size:
        raise FileUploadError(f"头像大小不能超过 {max_size // (1024 * 1024)}MB")
    if mime == "image/webp":
        if raw_bytes[:4] != b"RIFF" or raw_bytes[8:12] != b"WEBP":
            raise FileUploadError("头像不是有效的 WEBP 图片")
    else:
        sig = _ALLOWED_AVATAR_MIME[mime]
        if raw_bytes[: len(sig)] != sig:
            raise FileUploadError("头像实际内容与声明的格式不符（可能被伪造）")
    return raw


def allowed_file(filename, allowed_extensions=None):
    """
    检查文件扩展名是否允许

    Args:
        filename: 文件名
        allowed_extensions: 允许的扩展名集合，默认允许图片扩展名

    Returns:
        True表示允许，False表示不允许
    """
    if allowed_extensions is None:
        allowed_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

    return "." in filename and os.path.splitext(filename)[1].lower() in allowed_extensions
