#!/usr/bin/env python3
"""
验证码识别模块
基于用户提供的方法：颜色分离 + OCR
支持两种类型的验证码：
1. 蓝底白字：保留高亮像素
2. 黑字浅底：保留暗色像素
"""

import os

import cv2
import pytesseract


class CaptchaRecognizer:
    """
    验证码识别器
    提供验证码自动识别功能
    """

    def __init__(self, tesseract_path=None):
        """
        初始化验证码识别器

        Args:
            tesseract_path (str): Tesseract OCR路径
        """
        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

    def recognize_captcha(self, captcha_path):
        """
        识别验证码

        Args:
            captcha_path (str): 验证码图片路径

        Returns:
            str: 识别的验证码
        """
        try:
            # 读取图片
            img = cv2.imread(captcha_path)
            if img is None:
                return None

            # 放大图片3倍，提高识别率
            img = cv2.resize(img, None, fx=3, fy=3)

            # 灰度化
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

            # 尝试两种二值化方法
            # 方法1：保留亮色（适用于蓝底白字）
            _, thresh1 = cv2.threshold(gray, 200, 255, cv2.THRESH_BINARY)

            # 方法2：保留暗色（适用于黑字浅底）
            _, thresh2 = cv2.threshold(gray, 120, 255, cv2.THRESH_BINARY_INV)

            # 形态学去噪
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            thresh1 = cv2.morphologyEx(thresh1, cv2.MORPH_OPEN, kernel)
            thresh2 = cv2.morphologyEx(thresh2, cv2.MORPH_OPEN, kernel)

            # 去噪
            thresh1 = cv2.medianBlur(thresh1, 3)
            thresh2 = cv2.medianBlur(thresh2, 3)

            # OCR配置
            config = "--psm 7 -c tessedit_char_whitelist=0123456789"

            # 尝试识别两种处理后的图片
            text1 = pytesseract.image_to_string(thresh1, config=config).strip()
            text2 = pytesseract.image_to_string(thresh2, config=config).strip()

            # 选择长度为4的数字作为结果
            for text in [text1, text2]:
                if text and text.isdigit() and len(text) == 4:
                    return text

            # 如果都不符合，返回长度最接近4的数字
            candidates = [text for text in [text1, text2] if text and text.isdigit()]
            if candidates:
                # 按长度排序，选择最接近4的
                candidates.sort(key=lambda x: abs(len(x) - 4))
                return candidates[0][:4] if len(candidates[0]) >= 4 else candidates[0]

            return None

        except Exception as e:
            print(f"验证码识别失败: {e}")
            return None


if __name__ == "__main__":
    # 测试验证码识别
    recognizer = CaptchaRecognizer()

    # 测试图片路径
    test_image = "output/temp/crawler/captcha.png"

    if os.path.exists(test_image):
        result = recognizer.recognize_captcha(test_image)
        print(f"验证码识别结果: {result}")
    else:
        print(f"测试图片不存在: {test_image}")
