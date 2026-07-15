#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课程表爬虫与处理主程序
整合登录、爬取、处理和图片生成功能
使用方式: python main.py
"""

import asyncio
import json
import os
import random
import re
import sys
from PIL import Image, ImageOps
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import io

try:
    import pytesseract
    # 从环境变量读取 Tesseract 路径（Linux 服务器需要）
    tesseract_cmd = os.environ.get('TESSERACT_CMD', '')
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

from config import CONFIG
from logger import get_logger


def _infer_semester_by_date():
    """教务系统学期下拉解析失败时，按当前日期推断当前学期。

    规则与后端 app.repository.course_repository.derive_current_semester 一致
    （秋季=第一学期 term1，春季=第二学期 term2）。生成本学期 course_meta 兜底，
    写入 raw/course_meta.json 后供全量爬取/前端学期下拉使用，打破「无元数据即
    无法爬取、爬取不了就永远没元数据」的死结。爬虫模块不 import app，故本地实现。
    """
    import datetime as _dt
    y, m = _dt.date.today().year, _dt.date.today().month
    if 9 <= m <= 12:
        start, term = y, 1
    elif 1 <= m <= 2:
        start, term = y - 1, 1
    else:  # 3 ~ 8 月为春季学期（第二学期）
        start, term = y - 1, 2
    name = f"{start}-{start + 1}-{term}"
    db_id = int(f"{start}{term}")
    eams_id = str(db_id)[-3:]
    return {
        'current_semester_id': eams_id,
        'current_semester_name': name,
        'weeks': list(range(1, 21)),
        'semesters': [{'id': eams_id, 'name': name}],
    }
from course_processing.process_course_data import CourseProcessor

# 可选：从教务系统导出的「全部」课表 xlsx 解析（作为整学期权威数据源，
# 因为网页端「全部」视图会漏渲染部分课程实例，xlsx 导出是服务端完整数据）。
try:
    from xlsx_import import parse_xlsx, merge_teacher_from_activities
    XLSX_IMPORT_AVAILABLE = True
except ImportError:
    XLSX_IMPORT_AVAILABLE = False
    print("警告: xlsx_import 模块导入失败，将仅使用网页端数据（可能漏周次）")

# 可选导入：图片生成模块（需要 matplotlib）
try:
    from course_processing.csv_to_image import CsvToImage
    IMAGE_GEN_AVAILABLE = True
except ImportError:
    IMAGE_GEN_AVAILABLE = False
    print("警告: csv_to_image 模块导入失败，图片生成功能不可用")


# 注入到教务系统页面的"反限流"脚本：从源头废掉"请不要过快点击"提示。
# 关键认知（来自真机验证）：
#   - eams 的"过快点击"只是一个**视觉警告**，不会阻断 searchTable 的提交与渲染
#     （用户实测：弹窗出来，表格照常渲染）。因此爬虫**绝不能**因检测到它而 reload/退避，
#     否则刚渲染好的数据会被覆盖、并陷入"刷新循环"。
#   - 这个脚本只负责"让弹窗看不见"，不负责也不需要阻止 searchTable。
# 做法：
#   1) 覆盖原生 alert/confirm/prompt 为空操作；
#   2) 覆盖常见 UI 库提示函数（layui layer / easyui $.messager / top/parent 中的同名函数）；
#   3) 主动轮询扫描 + MutationObserver 双保险，移除含"过快点击"/"不要频繁"文本的弹窗 DOM，
#      并自动点击其中的"确定/关闭"按钮。
_ANTI_THROTTLE_JS = r"""
() => {
    // 1. 禁用原生弹窗
    window.alert = function(){ return false; };
    window.confirm = function(){ return true; };
    window.prompt = function(){ return null; };

    // 2. 覆盖各种前端 UI 库的提示函数（eams 可能用 layui / easyui / 自封装）
    function _patch_ui(){
        try {
            if (window.layer) {
                window.layer.msg = function(){ return {close:function(){}}; };
                window.layer.alert = function(){ return {close:function(){}}; };
                window.layer.confirm = function(msg, yes){ if (typeof yes === 'function') yes(); };
                window.layer.closeAll = function(){};
            }
        } catch(e){}
        try {
            if (window.top && window.top.layer) {
                window.top.layer.msg = function(){ return {close:function(){}}; };
                window.top.layer.alert = function(){ return {close:function(){}}; };
                window.top.layer.closeAll = function(){};
            }
        } catch(e){}
        try {
            if (window.parent && window.parent.layer) {
                window.parent.layer.msg = function(){ return {close:function(){}}; };
                window.parent.layer.alert = function(){ return {close:function(){}}; };
                window.parent.layer.closeAll = function(){};
            }
        } catch(e){}
        try {
            if (window.$ && $.messager) {
                $.messager.alert = function(){};
                $.messager.show = function(){};
                $.messager.popup = function(){};
                $.messager.confirm = function(msg, yes){ if (typeof yes === 'function') yes(); };
                $.messager.popwin = function(){};
            }
        } catch(e){}
    }
    _patch_ui();
    setInterval(_patch_ui, 500);  // 高频补丁，防止 eams 重新赋值提示函数

    // 3. 自动移除/关闭"过快点击"/"不要频繁"弹窗
    var KEYWORDS = ['过快点击', '不要频繁', '操作过快', '请勿频繁'];
    function _remove_box(el){
        var box = el.closest(
            '[class*="dialog"],[class*="modal"],[class*="tip"],[class*="msg"],[class*="alert"],' +
            '[class*="layui-layer"],[class*="messager"],[class*="window"],[class*="panel"],[id*="dialog"],' +
            '[id*="message"],[id*="alert"],[class*="layui-m-layer"]'
        );
        if (box && box.parentNode){ box.parentNode.removeChild(box); return true; }
        if (el.parentNode){ el.parentNode.removeChild(el); return true; }
        return false;
    }
    function _scan(){
        try {
            var all = document.querySelectorAll('*');
            for (var i = 0; i < all.length; i++){
                var el = all[i];
                var t = el.textContent || '';
                if (!t) continue;
                var hit = false;
                for (var k = 0; k < KEYWORDS.length; k++){
                    if (t.indexOf(KEYWORDS[k]) !== -1){ hit = true; break; }
                }
                if (!hit) continue;
                // 先尝试点击"确定/关闭"按钮
                var btns = el.querySelectorAll('button,a,.layui-layer-btn a');
                var clicked = false;
                for (var b = 0; b < btns.length; b++){
                    var bt = (btns[b].textContent || '').trim();
                    if (bt.indexOf('确定') !== -1 || bt.indexOf('关闭') !== -1 || bt.indexOf('知道了') !== -1){
                        btns[b].click(); clicked = true; break;
                    }
                }
                if (!clicked) _remove_box(el);
            }
        } catch(e){}
    }
    setInterval(_scan, 300);  // 主动扫描移除，不依赖 MutationObserver 时机
    try {
        var obs = new MutationObserver(function(){ _scan(); });
        obs.observe(document.documentElement, {childList: true, subtree: true});
    } catch(e){}
}
"""


class CourseTableTool:
    """课程表获取工具"""
    
    def __init__(self, username, password, semester_id=None):
        self.username = username
        self.password = password
        self.semester_id = semester_id  # None = 爬取服务端默认（当前）学期
        self.logger = get_logger('main')
        self.course_data = None
    
    async def _download_and_recognize_captcha(self, page):
        """从当前页面会话下载并识别验证码"""
        try:
            # 从当前页面中查找验证码图片元素
            captcha_img = await page.query_selector('.account-form img[src*="captcha"]')
            
            if not captcha_img:
                self.logger.error("未找到验证码图片元素")
                return ""
            
            # 获取验证码图片的完整URL
            captcha_src = await captcha_img.get_attribute('src')
            self.logger.debug(f"验证码图片URL: {captcha_src}")
            
            # 使用当前页面的请求上下文获取验证码（保持会话）
            resp = await page.request.get(f"https://cas.cqie.cn{captcha_src}")
            
            if resp.ok:
                img = Image.open(io.BytesIO(await resp.body())).convert("L")
                img = ImageOps.invert(img)
                img = img.point(lambda p: p > 128 and 255)
                
                if OCR_AVAILABLE:
                    captcha = pytesseract.image_to_string(
                        img, 
                        config="--psm 8 -c tessedit_char_whitelist=0123456789"
                    )
                    # 只保留数字
                    captcha = ''.join([c for c in captcha if c.isdigit()]).strip()
                    # 验证是否为纯数字且长度符合要求
                    if captcha and len(captcha) >= 4 and captcha.isdigit():
                        return captcha
                    self.logger.warning(f"验证码不符合要求（非纯数字或长度不足）: {captcha if captcha else '空'}")
            else:
                self.logger.error(f"获取验证码图片失败: {resp.status}")
        except Exception as e:
            self.logger.error(f"验证码识别过程出错: {e}")
        
        return ""
    
    async def _check_login_error(self, page):
        """检查是否有登录错误提示"""
        try:
            # 查找错误提示元素
            error_element = await page.query_selector('.account-form .errorTitle span:first-child')
            if error_element:
                error_text = await error_element.inner_text()
                error_text = error_text.strip()
                if error_text:
                    self.logger.warning(f"检测到错误提示: {error_text}")
                    return error_text
        except Exception as e:
            self.logger.debug(f"检查错误提示时出错: {e}")
        return None

    async def _login(self, page, max_retries=3):
        """
        登录CAS系统，验证码识别失败时自动重试
        
        Args:
            page: Playwright页面对象
            max_retries: 最大重试次数（默认3次）
            
        Returns:
            bool: 登录成功返回True，否则返回False
        """
        login_url = "https://cas.cqie.cn/cas/WEB/index.html?service=http%3A%2F%2Fjwxt.cqie.cn%3A8081%2Feams%2FloginExt.action"
        
        for retry in range(max_retries):
            if retry > 0:
                self.logger.info(f"第 {retry} 次重试登录...")
                # 刷新页面，获取新验证码
                await page.reload(wait_until="domcontentloaded")
                await asyncio.sleep(2)
            
            self.logger.info("开始登录流程...")
            
            # 加载登录页面
            await page.goto(login_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(2)
            
            # 识别验证码
            captcha = await self._download_and_recognize_captcha(page)
            self.logger.info(f"验证码识别结果: {captcha if captcha else '未识别'}")
            
            # 如果验证码不符合要求，重试
            if not captcha or len(captcha) < 4 or not captcha.isdigit():
                self.logger.warning(f"[重试 {retry + 1}/{max_retries}] 验证码识别失败（非纯数字或长度不足），正在重试...")
                continue
            
            # 填写表单
            self.logger.info("填写登录表单...")
            await page.fill('input[type="text"]', self.username)
            await page.fill('input[type="password"]', self.password)
            await page.fill('input[placeholder="验证码"]', captcha)
            
            # 点击登录
            self.logger.info("点击登录...")
            login_btn = await page.query_selector('.login-button')
            if login_btn:
                # 改用 Playwright 原生点击：自动等待按钮可见/稳定/可点，并派发真实鼠标事件，
                # 避免 evaluate('btn.click()') 这种瞬时合成点击被教务系统判定为“过快点击”。
                await login_btn.click()
            
            # 等待页面响应
            await asyncio.sleep(2)
            
            # 检查是否有错误提示
            error_text = await self._check_login_error(page)
            if error_text:
                if "验证码错误" in error_text:
                    self.logger.warning(f"[重试 {retry + 1}/{max_retries}] 验证码错误，正在重试...")
                    continue
                elif "账号或密码错误" in error_text:
                    self.logger.error("[失败] 账号或密码错误！请检查config.py中的配置！程序将退出！")
                    return False
                else:
                    self.logger.error(f"[失败] 登录失败: {error_text}，程序将退出，请重新运行！")
                    return False
            
            # 等待登录结果（最多等待30秒）
            self.logger.info("等待登录结果...")
            login_success = False
            
            for i in range(30):
                if "jwxt" in page.url and "login" not in page.url.lower():
                    self.logger.info("[成功] 登录成功！")
                    login_success = True
                    break
                await asyncio.sleep(1)
                
                # 每5秒检查一次错误提示
                if i % 5 == 0 and i > 0:
                    error_text = await self._check_login_error(page)
                    if error_text:
                        if "验证码错误" in error_text:
                            self.logger.warning(f"[重试 {retry + 1}/{max_retries}] 验证码错误，正在重试...")
                            break  # 跳出内层循环，进入下一次重试
                        elif "账号或密码错误" in error_text:
                            self.logger.error("[失败] 账号或密码错误！请检查config.py中的配置！程序将退出！")
                            return False
            
            if login_success:
                # 登录成功后缓冲：CAS 刚刚建立会话，若立即发起下一跳（goto 课表页），
                # 教务系统会判定为“过快点击”并掐断访问。模拟真人登录后停顿片刻，
                # 等门户首页真正稳定后再放行后续导航，规避“进去第一刻就被掐”。
                try:
                    await page.wait_for_load_state('networkidle', timeout=15000)
                except Exception:
                    pass
                await asyncio.sleep(random.uniform(3, 7))
                self.logger.info("登录后缓冲完成，准备进入课表页...")
                return True
            
            # 如果内层循环结束后仍未成功，检查是否需要重试
            error_text = await self._check_login_error(page)
            if error_text and "验证码错误" in error_text:
                continue  # 重试
        
        self.logger.error(f"[失败] 登录失败（已重试{max_retries}次），程序将退出，请重新运行！")
        return False

    async def _goto_course_table(self, page, max_retries=4):
        """进入课程表页面，带“过快点击/访问受限”拦截检测与退避重试。

        登录成功后若立即访问深层 action，教务服务端会判定“过快点击”并拒绝响应
        （页面显示过快点击且课表不渲染）。此时不能硬解析，必须退避更久后重试。

        注意与「选周后渲染阶段的过快点击弹窗」区分：后者仅是视觉警告、数据照常渲染，
        由 _ANTI_THROTTLE_JS 压制且严禁退避（退避会覆盖已渲染数据）；本方法只用于
        「进页面」阶段，且以“是否真正进入课表页”为判据，而非见到弹窗就退避。
        """
        url = "http://jwxt.cqie.cn:8081/eams/courseTableForStd.action"
        for attempt in range(1, max_retries + 1):
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            except Exception as e:
                self.logger.warning(f"访问课程页面异常（第 {attempt}/{max_retries} 次）: {e}")
                await asyncio.sleep(5 * attempt)
                continue
            await asyncio.sleep(2)
            html = await page.content() or ""
            # 真正进入课表页的标志：教学周下拉 / 课表容器 / TaskActivity
            entered = ('startWeek' in html) or ('TaskActivity' in html) or ('课程表' in html)
            if not entered:
                self.logger.warning(
                    f"进课程页面疑似被过快点击/访问受限拦截（第 {attempt}/{max_retries} 次），"
                    f"退避 {8 * attempt}s 后重试..."
                )
                await asyncio.sleep(8 * attempt)
                continue
            self.logger.info("成功进入课程页面")
            return True
        self.logger.error("多次重试仍无法进入课程页面（过快点击拦截）")
        return False

    def _parse_course_table(self, html, teacher_mapping=None):
        """
        解析课程表HTML为标准格式 (headers + rows)
        
        Args:
            html: 课程表HTML
            teacher_mapping: 教师姓名映射（可选），格式为 {课程代码: 教师姓名}
        """
        soup = BeautifulSoup(html, 'html.parser')
        tables = soup.find_all('table')
        
        for table in tables:
            rows = table.find_all('tr')
            if len(rows) > 5:
                header = rows[0].get_text(strip=True)
                if '节次' in header and '星期' in header:
                    return self._extract_schedule(rows, teacher_mapping)
        
        return None
    
    def _extract_teacher_mapping_from_html(self, html):
        """
        从HTML的JavaScript代码中提取教师姓名映射
        
        解析TaskActivity调用，提取课程代码和教师姓名的对应关系
        
        Returns:
            dict: {课程代码: 教师姓名}
        """
        teacher_mapping = {}
        
        # 使用正则表达式查找所有的TaskActivity调用
        # 示例: activity = new TaskActivity(actTeacherId.join(','),actTeacherName.join(','),"188444(220110460.02)","课程名",...)
        pattern = r'new TaskActivity\([^,]+,\s*([^,]+),\s*["\']([^"\']+)["\']'
        matches = re.findall(pattern, html)
        
        for match in matches:
            teacher_names_expr = match[0].strip()  # actTeacherName.join(',')
            course_code_full = match[1].strip()  # "188444(220110460.02)"
            
            # 提取课程代码（去掉前面的数字）
            # "188444(220110460.02)" -> "220110460.02"
            code_match = re.search(r'\(([^)]+)\)', course_code_full)
            if code_match:
                course_code = code_match.group(1)
                
                # 尝试从JavaScript表达式中提取教师姓名
                # actTeacherName 是一个JavaScript变量，我们需要在页面上下文中执行JavaScript来获取它的值
                # 但这里我们只是解析HTML，所以无法执行JavaScript
                
                # 暂时留空，等待后续改进
                teacher_mapping[course_code] = ''
        
        return teacher_mapping
    
    def _extract_schedule(self, rows, teacher_mapping=None):
        """
        提取课程表数据为 headers + rows 格式，正确处理 rowspan 跨节课程
        
        Args:
            rows: HTML表格行
            teacher_mapping: 教师姓名映射（可选），格式为 {课程代码: 教师姓名}
        """
        day_names = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
        
        headers = ['节次/周次'] + day_names
        
        course_rows = []
        # 用于跟踪每列的 rowspan 填充情况
        # rowspan_tracker[列索引] = (课程内容, 剩余行数)
        rowspan_tracker = {}
        
        for row in rows:
            row_data = []
            cells = row.find_all(['td', 'th'])
            
            # 跳过打印预览行（第一行通常包含"打印预览"或"节次/周次"混合的乱码）
            first_cell_text = cells[0].get_text(strip=True) if cells else ''
            if '打印预览' in first_cell_text or len(first_cell_text) > 20:
                continue
            if first_cell_text == '节次/周次' and len(cells) > 8:
                continue
            
            # 处理每个单元格，考虑 rowspan
            col_idx = 0
            for cell in cells:
                # 先检查当前位置是否需要填充 rowspan 内容
                while col_idx in rowspan_tracker:
                    content, remaining = rowspan_tracker[col_idx]
                    row_data.append(content)
                    if remaining > 1:
                        rowspan_tracker[col_idx] = (content, remaining - 1)
                    else:
                        del rowspan_tracker[col_idx]
                    col_idx += 1
                
                # 获取当前单元格内容
                cell_text = cell.get_text(strip=True)
                rowspan = int(cell.get('rowspan', 1))
                
                # 如果提供了教师映射，尝试为缺失教师的课程补全教师
                if teacher_mapping and cell_text:
                    # 从 cell_text 中提取课程代码，形如 (220110460.02)
                    code_m = re.search(r'\(([A-Za-z0-9]+\.[0-9]+)\)', cell_text)
                    if code_m:
                        course_code = code_m.group(1)
                        teacher_name = teacher_mapping.get(course_code)
                        if teacher_name and teacher_name not in cell_text:
                            # 在「课程名(代码)」之后插入「(教师)」，
                            # 形如 课程名(代码)(教师) \n([周次]周,教室)
                            # _extract_course_info 即可解析出教师字段
                            insert_at = code_m.end()
                            cell_text = cell_text[:insert_at] + f"({teacher_name})" + cell_text[insert_at:]
                
                if rowspan > 1:
                    # 记录 rowspan 信息，用于后续行填充
                    rowspan_tracker[col_idx] = (cell_text, rowspan - 1)
                
                row_data.append(cell_text)
                col_idx += 1
            
            # 填充剩余的 rowspan 列
            while col_idx in rowspan_tracker:
                content, remaining = rowspan_tracker[col_idx]
                row_data.append(content)
                if remaining > 1:
                    rowspan_tracker[col_idx] = (content, remaining - 1)
                else:
                    del rowspan_tracker[col_idx]
                col_idx += 1
            
            course_rows.append(row_data)
        
        return {
            'headers': headers,
            'rows': course_rows
        }
    
    # ------------------------------------------------------------------
    # 升级版 Plan A：直接解析页面 JavaScript 中的 TaskActivity，
    # 一次请求即可拿到整学期的课程安排（周次位图 + 精确节次 + 教师），
    # 无需按周切换，从根本上避免"过快点击"限流。
    # ------------------------------------------------------------------
    def _split_js_args(self, s):
        """
        按顶层逗号切分 JavaScript 函数实参字符串。
        
        会正确跳过字符串字面量与括号（()/[]/{}）内部的逗号，
        因此像 new TaskActivity(a,b,"x(y)",...) 这样的调用能被正确拆分。
        
        Args:
            s: TaskActivity(...) 括号内的原始实参字符串
        
        Returns:
            list: 拆分后的实参列表（保留原始引号，未去引号）
        """
        args = []          # 拆分结果
        buf = []           # 当前实参的字符缓冲
        depth = 0          # 括号嵌套深度
        in_str = False     # 是否处于字符串字面量中
        quote = ''         # 当前字符串使用的引号字符
        escaped = False    # 上一个字符是否为转义符 '\'
        
        for ch in s:
            if in_str:
                # 字符串内部：仅关注转义与闭合引号
                buf.append(ch)
                if escaped:
                    escaped = False
                elif ch == '\\':
                    escaped = True
                elif ch == quote:
                    in_str = False
                continue
            
            if ch in ('"', "'"):
                in_str = True
                quote = ch
                buf.append(ch)
            elif ch in ('(', '[', '{'):
                depth += 1
                buf.append(ch)
            elif ch in (')', ']', '}'):
                depth -= 1
                buf.append(ch)
            elif ch == ',' and depth == 0:
                # 顶层逗号：切分出一个实参
                args.append(''.join(buf).strip())
                buf = []
            else:
                buf.append(ch)
        
        if buf:
            args.append(''.join(buf).strip())
        
        return args
    
    def _unquote(self, s):
        """去掉字符串两端成对的引号"""
        s = s.strip()
        if len(s) >= 2 and s[0] in ('"', "'") and s[-1] == s[0]:
            return s[1:-1]
        return s
    
    def _weeks_bitmap_to_str(self, bitmap):
        """
        将整学期周次位图转换为紧凑区间字符串。
        
        位图为 '0'/'1' 组成的字符串，下标即周次号（下标 0 不使用，
        下标 19 为 '1' 表示第 19 周有课）。
        
        示例:
            '...1...'(仅第19位为1) -> '19'
            连续 1-16 周           -> '1-16'
            1-8 与 10-16 周        -> '1-8 10-16'
        
        Args:
            bitmap: 周次位图字符串
        
        Returns:
            str: 紧凑周次区间字符串，无课时返回空串
        """
        weeks = [i for i, ch in enumerate(bitmap) if ch == '1']
        if not weeks:
            return ''
        
        parts = []
        start = prev = weeks[0]
        for w in weeks[1:]:
            if w == prev + 1:
                # 周次连续，延伸当前区间
                prev = w
            else:
                # 出现断点，收尾当前区间并开启新区间
                parts.append(f"{start}-{prev}" if start != prev else f"{start}")
                start = prev = w
        parts.append(f"{start}-{prev}" if start != prev else f"{start}")
        
        return ' '.join(parts)
    
    def _expand_weeks_str(self, weeks_str):
        """
        将紧凑周次区间字符串展开为周次数字集合。
        
        示例: '2-5 7 9 11 12-18' -> {2,3,4,5,7,9,11,12,...,18}
        
        Args:
            weeks_str: _weeks_bitmap_to_str 的输出
            
        Returns:
            set: 周次数字集合
        """
        weeks = set()
        if not weeks_str:
            return weeks
        for part in weeks_str.split():
            if '-' in part:
                m = re.match(r'(\d+)-(\d+)', part)
                if m:
                    a, b = int(m.group(1)), int(m.group(2))
                    weeks.update(range(a, b + 1))
            else:
                m = re.match(r'(\d+)', part)
                if m:
                    weeks.add(int(m.group(1)))
        return weeks
    
    def _count_distinct_weeks(self, activities):
        """
        统计解析出的课程活动覆盖了多少个不同的教学周。
        
        用于在"全部"视图渲染后校验是否真的拿到了整学期数据
        （而非只拿到默认当前周）。
        
        Args:
            activities: _parse_activities 返回的课程活动列表
            
        Returns:
            int: 覆盖的不同教学周数量
        """
        weeks = set()
        for act in activities:
            weeks.update(self._expand_weeks_str(act.get('weeks_str', '')))
        return len(weeks)
    
    def _parse_activities(self, html):
        """
        从课表页 HTML 的 JavaScript 中解析所有 TaskActivity，得到整学期课程安排。
        
        eams 页面用 new TaskActivity(...) 描述每一门课，实参含义（下标）：
            [2] 任务号(课程代码)   如 "188443(230111470.01)"
            [3] 课程名(含<sup>标签及尾部课程代码)
            [5] 教室(已含"(校本部)")
            [6] 整学期周次位图
        每个 TaskActivity 之前有 var actTeachers=[...] 描述授课教师，
        之后有若干 index=星期*unitCount+节次 描述其占用的格子。
        
        Args:
            html: 课表页完整 HTML
        
        Returns:
            tuple: (activities, unit_count)
                activities: list[dict]，每项含
                    code / course_name / teacher / room / weeks_str / slots
                    slots 为 [(day, period), ...]，day 从 0 起(0=星期一)，
                    period 从 0 起(0=第一节)
                unit_count: 每天节次数（默认 12）
        """
        activities = []
        
        # 解析每天节次数 unitCount，缺省 12
        m_unit = re.search(r'var\s+unitCount\s*=\s*(\d+)', html)
        unit_count = int(m_unit.group(1)) if m_unit else 12
        
        # 定位所有 new TaskActivity(...) 调用
        ta_iter = list(re.finditer(r'new\s+TaskActivity\((.*?)\)\s*;', html, re.DOTALL))
        
        for i, m in enumerate(ta_iter):
            args = self._split_js_args(m.group(1))
            if len(args) < 7:
                # 参数不足，跳过异常调用
                continue
            
            # 课程代码：从 "188443(230111470.01)" 中取括号内内容
            code_raw = self._unquote(args[2])
            code_m = re.search(r'\(([^)]+)\)', code_raw)
            code = code_m.group(1) if code_m else code_raw
            
            # 课程名：去掉 HTML 标签与尾部 "(课程代码)"
            name_raw = self._unquote(args[3])
            name_raw = re.sub(r'<[^>]+>', '', name_raw)
            course_name = re.sub(r'\([^)]*\)\s*$', '', name_raw).strip()
            
            # 教室（已含"(校本部)"）与整学期周次位图
            room = self._unquote(args[5])
            bitmap = self._unquote(args[6])
            weeks_str = self._weeks_bitmap_to_str(bitmap)
            
            # 授课教师：取本次调用之前最近的 actTeachers 定义
            block_start = ta_iter[i - 1].end() if i > 0 else 0
            block = html[block_start:m.start()]
            teacher = ''
            act_blocks = re.findall(r'var\s+actTeachers\s*=\s*\[(.*?)\]\s*;', block, re.DOTALL)
            if act_blocks:
                names = re.findall(r'name\s*:\s*"([^"]*)"', act_blocks[-1])
                teacher = ','.join(names)
            
            # 占用格子：本次调用之后到下一次调用之前的 index=星期*unitCount+节次
            seg_end = ta_iter[i + 1].start() if i + 1 < len(ta_iter) else len(html)
            seg = html[m.end():seg_end]
            slots = [(int(d), int(p)) for d, p in
                     re.findall(r'index\s*=\s*(\d+)\s*\*\s*unitCount\s*\+\s*(\d+)', seg)]
            
            activities.append({
                'code': code,
                'course_name': course_name,
                'teacher': teacher,
                'room': room,
                'weeks_str': weeks_str,
                'slots': slots
            })
        
        return activities, unit_count
    
    def _build_grid_from_activities(self, activities, unit_count=12):
        """
        将解析出的 TaskActivity 列表重建为处理层可消费的 {headers, rows} 表格。
        
        输出结构与按周渲染的表格完全一致：
            rows[0]      表头 ['节次/周次','星期一'..'星期日']
            rows[1..N]   每节一行，首列为节次名"第一节".."第十二节"
        单元格文本形如：课程名(代码) (教师)([周次]周,教室(校本部))
        （与处理层 _extract_course_info 的正则完全兼容）
        
        Args:
            activities: _parse_activities 返回的课程活动列表
            unit_count: 每天节次数（默认 12）
        
        Returns:
            dict: {'headers': [...], 'rows': [[...], ...]}
        """
        day_names = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
        cn_num = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']
        headers = ['节次/周次'] + day_names
        
        # 初始化空表格：首行表头，其后每节一行
        rows = [headers[:]]
        for p in range(unit_count):
            period_name = f"第{cn_num[p]}节" if p < len(cn_num) else f"第{p + 1}节"
            rows.append([period_name] + [''] * len(day_names))
        
        # 逐门课填入其占用的格子
        for act in activities:
            teacher_part = f" ({act['teacher']})" if act['teacher'] else ''
            cell = (f"{act['course_name']}({act['code']}){teacher_part}"
                    f"([{act['weeks_str']}]周,{act['room']})")
            for day, period in act['slots']:
                if 0 <= day < len(day_names) and 0 <= period < unit_count:
                    row = rows[period + 1]   # +1 跳过表头行
                    col = day + 1            # +1 跳过节次列
                    if row[col]:
                        # 同一格多门课，用空行分隔
                        row[col] += '\n\n' + cell
                    else:
                        row[col] = cell
        
        return {'headers': headers, 'rows': rows}

    def _find_xlsx_source(self):
        """
        查找教务系统导出的「全部」课表 xlsx（整学期权威数据源）。
        依次尝试多个候选路径，返回命中路径或 None。
        """
        candidates = [
            os.environ.get('XLSX_COURSE_PATH', ''),
            os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         'output', 'course-data', 'raw', '课表.xlsx'),
            r'C:/Users/blueberry/Downloads/课表.xlsx',
        ]
        for p in candidates:
            if p and os.path.exists(p):
                return p
        return None

    async def _download_xlsx_export(self, page, save_dir):
        """
        点击课表页的「导出」入口，下载 xlsx 作为整学期权威数据源。
        必须在已选择教学周「全部」之后调用（此时导出的才是整学期完整数据）。

        eams 课程表页通常带有「导出」链接/按钮（强智 eams 一般为导出 xlsx）。
        本方法自动定位入口、触发下载并保存，失败或导出为旧版 .xls 时返回 None（回退网页端数据）。

        Returns:
            str | None: 下载到的 xlsx 文件路径；失败返回 None。
        """
        self.logger.info("尝试定位课表页的「导出」入口（整学期权威数据源）...")
        # 1) 给所有疑似导出入口打标 data-cqie-export
        #    扫描 a/button/input/form，匹配文本及全部属性（含 id/name/class/value/action/href/onclick），
        #    以覆盖「导出」按钮（<input type=submit value=导出>）与导出表单（<form id=exportTableForm>）。
        await page.evaluate("""() => {
            const want = /导出|export|xlsx|xls|download|下载/i;
            const attrs = (el) => {
                let s = '';
                for (let i = 0; i < el.attributes.length; i++) {
                    s += el.attributes[i].name + '=' + el.attributes[i].value + ' ';
                }
                return s;
            };
            document.querySelectorAll('a, button, input, form').forEach(el => {
                const blob = ((el.textContent || '') + ' ' + attrs(el)).toLowerCase();
                if (want.test(blob)) {
                    if (el.getAttribute('data-cqie-export') === null) {
                        const n = document.querySelectorAll('[data-cqie-export]').length;
                        el.setAttribute('data-cqie-export', String(n));
                    }
                }
            });
        }""")
        count = await page.evaluate("() => document.querySelectorAll('[data-cqie-export]').length")
        if count == 0:
            self.logger.warning("未找到任何「导出」入口，将回退到网页端数据")
            return None
        self.logger.info(f"发现 {count} 个疑似导出入口，详情: " + json.dumps(
            await page.evaluate("""() => Array.from(document.querySelectorAll('[data-cqie-export]')).map(el => ({
                tag: el.tagName,
                text: (el.textContent||'').trim(),
                id: el.id||'',
                value: el.getAttribute('value')||'',
                href: el.getAttribute('href')||'',
                action: el.getAttribute('action')||'',
                onclick: (el.getAttribute('onclick')||'').slice(0,80)
            }))"""),
            ensure_ascii=False
        ))

        # 2) 选出最可能是「整学期 xlsx 导出」的入口
        #    优先：导出表单 exportTableForm 的提交按钮（eams 真实入口，客户端 xlsxStyle 生成下载）
        chosen = None
        form_el = await page.query_selector('#exportTableForm')
        if form_el:
            btn = await form_el.query_selector('input[type="submit"], button[type="submit"], input[type="button"], button')
            if btn:
                chosen = btn
                self.logger.info("命中 exportTableForm 的提交按钮，将点击触发客户端导出")
        if not chosen:
            handles = await page.query_selector_all("[data-cqie-export]")
            # 优先级：xlsx > export/导出 > .xls > 第一个
            for h in handles:
                txt = (await h.inner_text() or '').lower()
                href = (await h.get_attribute('href') or '').lower()
                onclick = (await h.get_attribute('onclick') or '').lower()
                val = (await h.get_attribute('value') or '').lower()
                if 'xlsx' in (txt + href + onclick + val):
                    chosen = h
                    break
            if not chosen:
                for h in handles:
                    txt = (await h.inner_text() or '').lower()
                    val = (await h.get_attribute('value') or '').lower()
                    onclick = (await h.get_attribute('onclick') or '').lower()
                    if 'export' in (txt + onclick + val) or '导出' in (txt + val):
                        chosen = h
                        break
            if not chosen:
                for h in handles:
                    href = (await h.get_attribute('href') or '').lower()
                    if '.xls' in href:
                        chosen = h
                        break
            if not chosen:
                chosen = handles[0]
        self.logger.info(
            f"选定导出入口: 标签={await chosen.evaluate('el => el.tagName')!r} "
            f"文本={await chosen.inner_text()!r} href={await chosen.get_attribute('href')!r}"
        )

        # 3) 触发下载（导出的是当前「全部」视图的整学期数据）
        os.makedirs(save_dir, exist_ok=True)
        save_path = os.path.join(save_dir, '课表.xlsx')
        try:
            href = (await chosen.get_attribute('href') or '').strip()
            # 若入口是 URL 链接，用隔离的新标签页直接访问，避免导航走主课表页（仍保留「全部」视图）；
            # 否则（按钮/onclick）直接点击。
            _BASE = "http://jwxt.cqie.cn:8081"
            if href and not href.lower().startswith('javascript'):
                if href.startswith('http'):
                    full_url = href
                elif href.startswith('/'):
                    full_url = _BASE + href
                else:
                    full_url = _BASE + '/' + href.lstrip('/')
                self.logger.info(f"通过隔离新标签页访问导出链接: {full_url}")
                dl_page = await page.context.new_page()
                try:
                    async with page.context.expect_download(timeout=45000) as dl_info:
                        await dl_page.goto(full_url, wait_until="domcontentloaded", timeout=45000)
                    download = await dl_info.value
                finally:
                    await dl_page.close()
            else:
                # 表单自身（无独立提交按钮）用 requestSubmit 触发 JS 导出逻辑；
                # 否则（按钮/input）直接点击。均用 context 级监听捕获下载。
                tag = await chosen.evaluate("el => el.tagName")
                async with page.context.expect_download(timeout=45000) as dl_info:
                    if tag == 'FORM':
                        # 优先点击表单内的真实提交按钮（原生 click，带等待）；
                        # 仅当表单内确实没有提交按钮时，才退化为 requestSubmit 触发 JS 导出逻辑。
                        submit_btn = await chosen.query_selector('button[type="submit"], input[type="submit"]')
                        if submit_btn:
                            await submit_btn.click()
                        else:
                            await chosen.evaluate("el => el.requestSubmit()")
                    else:
                        await chosen.click()
                download = await dl_info.value
            suggested = download.suggested_filename or '课表.xlsx'
            self.logger.info(f"导出触发成功，建议文件名: {suggested}")
            low = suggested.lower()
            if low.endswith('.xls') and not low.endswith('.xlsx'):
                # 旧版二进制 .xls（BIFF），当前 zipfile+xml 解析器不支持
                xls_path = os.path.join(save_dir, '课表.xls')
                await download.save_as(xls_path)
                self.logger.warning(
                    f"导出文件为 .xls（非 xlsx），当前解析器不支持，"
                    f"已保存至 {xls_path}，将回退网页端数据"
                )
                return None
            await download.save_as(save_path)
            if not os.path.exists(save_path):
                self.logger.warning("导出文件保存后未找到，回退网页端数据")
                return None
            self.logger.info(f"已自动导出 xlsx 到 {save_path}")
            return save_path
        except Exception as e:
            self.logger.warning(f"触发导出下载失败（将回退网页端数据）: {e}")
            return None

    def _build_grid_from_xlsx(self, xlsx_courses, unit_count=12):
        """
        由 xlsx 解析出的课程实例列表重建处理层可消费的 {headers, rows} 表格。
        结构与 _build_grid_from_activities 完全一致，每个单元格文本形如：
            课程名(代码) (教师)([周次]周,教室(校本部))
        其中周次用紧凑区间字符串（如 "2-5 7 9 11-18"）。
        """
        day_names = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
        cn_num = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十', '十一', '十二']
        headers = ['节次/周次'] + day_names

        rows = [headers[:]]
        for p in range(unit_count):
            period_name = f"第{cn_num[p]}节" if p < len(cn_num) else f"第{p + 1}节"
            rows.append([period_name] + [''] * len(day_names))

        def _weeks_to_str(weeks):
            if not weeks:
                return ''
            parts = []
            start = prev = weeks[0]
            for w in weeks[1:]:
                if w == prev + 1:
                    prev = w
                else:
                    parts.append(f"{start}-{prev}" if start != prev else f"{start}")
                    start = prev = w
            parts.append(f"{start}-{prev}" if start != prev else f"{start}")
            return ' '.join(parts)

        for c in xlsx_courses:
            teacher_part = f" ({c['teacher']})" if c.get('teacher') else ''
            weeks_str = _weeks_to_str(c['weeks'])
            cell = (f"{c['course_name']}({c['course_code']}){teacher_part}"
                    f"([{weeks_str}]周,{c.get('classroom', '')})")
            day = c['week_day'] - 1  # 1-based -> 0-based
            period = c['period_idx'] - 1
            if 0 <= day < len(day_names) and 0 <= period < unit_count:
                row = rows[period + 1]
                col = day + 1
                if row[col]:
                    row[col] += '\n\n' + cell
                else:
                    row[col] = cell

        return {'headers': headers, 'rows': rows}

    def _save_raw_data(self, course_data, html, all_weeks=False):
        """保存原始数据"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        raw_data_dir = os.path.join(script_dir, CONFIG['processing']['raw_data_dir'])
        # 【学期隔离】若指定了学期，数据落到 semester_<id>/ 子目录，避免覆盖当前学期
        if self.semester_id:
            raw_data_dir = os.path.join(raw_data_dir, f'semester_{self.semester_id}')
        os.makedirs(raw_data_dir, exist_ok=True)
        
        # 保存HTML（如果提供）
        if html:
            html_path = os.path.join(raw_data_dir, 'course_table.html')
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(html)
            self.logger.info(f"原始HTML已保存: {html_path}")
        
        # 保存JSON
        json_path = os.path.join(raw_data_dir, 'course_table.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(course_data, f, ensure_ascii=False, indent=2)
        self.logger.info(f"原始JSON已保存: {json_path}")
        
        # 如果是所有周次的数据，还保存一个副本
        if all_weeks:
            all_weeks_path = os.path.join(raw_data_dir, 'course_table_all_weeks.json')
            with open(all_weeks_path, 'w', encoding='utf-8') as f:
                json.dump(course_data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"所有周次数据已保存: {all_weeks_path}")
        
        # 同时保存到脚本根目录（供其他模块读取）
        root_json_path = os.path.join(script_dir, 'course_table.json')
        with open(root_json_path, 'w', encoding='utf-8') as f:
            json.dump(course_data, f, ensure_ascii=False, indent=2)

    async def _extract_semesters(self, page):
        """
        从课表页的学期下拉框解析全部可选学期 + 当前学期。

        EAMS courseTableForStd.action 页面带一个学期 <select>（选项 value=学期 eams_id，
        如 "251"；文本=学期名，如 "2025-2026-1"；当前学期选项带 selected）。

        普通爬虫（爬当日课程）加载该页即可拿到完整学期列表，从而自动维护
        course_meta.json——全量爬取预约（_crawl_all_semesters）依赖此文件提供学期列表，
        课程管理前端的学期下拉也读它。这样无需额外的生成步骤，学期数据随日常爬取自愈。

        Returns:
            dict | None: {
                'current_semester_id': str,    # eams id，如 "251"
                'current_semester_name': str,  # 如 "2025-2026-1"
                'weeks': [int, ...],
                'semesters': [{'id': str, 'name': str}, ...]
            } 解析失败时返回 None
        """
        try:
            select_el = None
            # 1) 优先按已知选择器定位学期 <select>
            for sel in ('select[name="semester.id"]', 'select[name*="semester"]',
                        '#semesterBar', 'select#semesterBar'):
                el = await page.query_selector(sel)
                if el:
                    select_el = el
                    break
            # 2) 退路：扫描所有 select，找选项文本含 "YYYY-YYYY" 学期名的那个
            if select_el is None:
                for sel in await page.query_selector_all('select'):
                    opts = await sel.query_selector_all('option')
                    for o in opts:
                        txt = await o.inner_text() or ''
                        if re.search(r'\d{4}[-/]\d{4}', txt):
                            select_el = sel
                            break
                    if select_el:
                        break
            if select_el is None:
                self.logger.warning("未找到学期下拉框，按当前日期推断学期兜底")
                return _infer_semester_by_date()

            opts = await select_el.query_selector_all('option')
            semesters = []
            current_id = None
            current_name = None
            for o in opts:
                val = (await o.get_attribute('value') or '').strip()
                if not val:
                    continue
                name = (await o.inner_text() or '').strip()
                # 去掉末尾的 "(1)"/"(2)" 学期序号后缀
                name_clean = re.sub(r'\(\d+\)$', '', name).strip() or name
                semesters.append({'id': val, 'name': name_clean})
                if await o.is_selected():
                    current_id, current_name = val, name_clean
            if not semesters:
                self.logger.warning("学期下拉框无选项，按当前日期推断学期兜底")
                return _infer_semester_by_date()
            if current_id is None:
                current_id, current_name = semesters[0]['id'], semesters[0]['name']

            # 周次列表：尝试从教学周下拉取，否则默认 1..20（与 --max-weeks 默认一致）
            weeks = list(range(1, 21))
            for wsel in ('select[name="week.id"]', 'select[name*="week"]', '#weekBar'):
                wsel_el = await page.query_selector(wsel)
                if wsel_el:
                    try:
                        wvals = [int((await wo.get_attribute('value') or '').strip())
                                 for wo in await wsel_el.query_selector_all('option')
                                 if (await wo.get_attribute('value') or '').strip().isdigit()]
                        if wvals:
                            weeks = sorted(set(wvals))
                            break
                    except Exception:
                        pass

            return {
                'current_semester_id': current_id,
                'current_semester_name': current_name,
                'weeks': weeks,
                'semesters': semesters,
            }
        except Exception as e:
            self.logger.warning(f"解析学期信息失败，按当前日期推断学期兜底: {e}")
            return _infer_semester_by_date()

    def _save_course_meta(self, meta):
        """将学期信息写入 raw/course_meta.json（合并式，幂等）。

        始终写到 raw 基目录（非 semester_<id> 子目录），与
        app/api/course_routes.py:get_semesters 的读取路径保持一致。

        合并策略：保留文件中已有的学期列表（按 id 去重），仅更新
        current_semester_id / current_semester_name / weeks，并追加本次新解析出的
        学期。这样即使本次解析因页面结构变化仅回退到单学期（_infer_semester_by_date），
        也不会把历史已收集的其它学期覆盖掉，避免「全量爬取越爬越少」。
        """
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            raw_data_dir = os.path.join(script_dir, CONFIG['processing']['raw_data_dir'])
            os.makedirs(raw_data_dir, exist_ok=True)
            meta_path = os.path.join(raw_data_dir, 'course_meta.json')

            # 读取已有学期列表，按 id 去重保留
            existing = {}
            if os.path.exists(meta_path):
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        old = json.load(f)
                    for s in old.get('semesters', []):
                        sid = str(s.get('id', '')).strip()
                        if sid:
                            existing[sid] = s
                except Exception:
                    pass

            # 合并本次解析出的学期（本次优先，避免被旧脏数据覆盖）
            for s in meta.get('semesters', []):
                sid = str(s.get('id', '')).strip()
                if sid:
                    existing[sid] = s

            merged = {
                'current_semester_id': meta.get('current_semester_id'),
                'current_semester_name': meta.get('current_semester_name'),
                'weeks': meta.get('weeks', list(range(1, 21))),
                'semesters': list(existing.values()),
            }
            with open(meta_path, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            self.logger.info(
                f"学期信息已合并写入 course_meta.json: 当前={merged['current_semester_name']}"
                f"（共 {len(merged['semesters'])} 个学期）"
            )
        except Exception as e:
            self.logger.warning(f"写入 course_meta.json 失败: {e}")

    async def _switch_semester(self, page, semester_id):
        """
        切换学期。

        eams 的学期切换本质是调用 `POST /eams/accessSemester!access.action`，
        把目标 semester.id 写入服务端 session。调用成功后，重新访问课表页
        （courseTableForStd.action）即会渲染该学期的数据。

        注意：本方法只负责"切换 + 重新加载 + 等待渲染"，不负责后续选"全部"/
        解析，那部分逻辑由调用方（get_course_table / _get_all_weeks_auto）复用。

        Args:
            page: Playwright 页面对象（已登录）
            semester_id: 目标学期 ID（字符串，如 "251"）

        Returns:
            bool: 是否切换成功（true 仅代表切换+重新加载执行无误，
                  不代表数据一定渲染完整，调用方需自行校验）
        """
        self.logger.info(f"切换学期（semester.id={semester_id}）...")

        try:
            # 1) 调用 eams 学期切换接口（模拟原页面 JS 的 $.ajax 调用）
            result = await page.evaluate(f"""async () => {{
                const resp = await fetch('/eams/accessSemester!access.action', {{
                    method: 'POST',
                    headers: {{'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'}},
                    body: new URLSearchParams({{
                        'pagePath': '/courseTableForStd.action',
                        'semester.id': '{semester_id}'
                    }})
                }});
                return await resp.text();
            }}""")
            self.logger.info(f"学期切换接口返回（前200字符）: {str(result)[:200]}")

            # 2) 重新加载课表页，使服务端 session 的新学期生效
            course_table_url = "http://jwxt.cqie.cn:8081/eams/courseTableForStd.action"
            await page.goto(course_table_url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(5)

            # 3) 等待课表 JS（含 TaskActivity）就绪——证明新学期数据已渲染
            #    注意：eams 服务器渲染较慢，且切换到已结束的学期（如上学期）后，
            #    首次加载的「当前周」视图可能延迟更久才注入 TaskActivity；
            #    真正的整学期数据要等「选全部」之后才渲染。此处仅做初步探测，
            #    不硬性失败——兜底交给主流程的「选全部 + 等渲染稳定」逻辑。
            html = ''
            for _ in range(60):
                await asyncio.sleep(1)
                html = await page.content()
                if 'TaskActivity' in html:
                    break

            if 'TaskActivity' not in html:
                self.logger.warning("切换学期后 60s 内未探测到 TaskActivity，交由主流程继续渲染（选全部后兜底）...")
            else:
                self.logger.info(f"学期切换完成：已加载 semester.id={semester_id} 的课表")

            # 不强制失败：即便此处未探测到 TaskActivity，主流程选「全部」后会
            # 重新渲染整学期课表（含 TaskActivity），可兜底。
            return True

        except Exception as e:
            self.logger.error(f"切换学期失败: {e}", exc_info=True)
            return False

    async def get_course_table(self):
        """获取课程表"""
        playwright = None
        browser = None
        
        try:
            playwright = await async_playwright().start()
            
            # 无头模式优化配置
            launch_options = {
                'headless': CONFIG['spider']['headless'],
                'args': [
                    '--disable-blink-features=AutomationControlled',  # 隐藏自动化特征
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-software-rasterizer',
                    '--disable-gpu'
                ]
            }
            
            browser = await playwright.chromium.launch(**launch_options)
            
            # 创建页面时添加真实浏览器指纹
            context_options = {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'locale': 'zh-CN',
                'timezone_id': 'Asia/Shanghai',
                'viewport': {'width': 1920, 'height': 1080},
                'color_scheme': 'light',
                'device_scale_factor': 1
            }
            
            context = await browser.new_context(**context_options)
            await context.add_init_script(_ANTI_THROTTLE_JS)
            page = await context.new_page()
            
            self.logger.info("正在登录...")
            if not await self._login(page):
                self.logger.error("登录失败，请手动登录")
                return None
            
            self.logger.info("正在获取课程表...")
            if not await self._goto_course_table(page):
                self.logger.error("进入课程页面失败，无法获取课表")
                return None
            await asyncio.sleep(2)

            # 【学期切换】若指定了非当前学期，先切换再解析
            if self.semester_id:
                if not await self._switch_semester(page, self.semester_id):
                    self.logger.error("学期切换失败，无法获取目标学期课表")
                    return None

            html = await page.content()

            # 【学期信息自动维护】普通爬虫（当日课程）顺手解析学期下拉，写 course_meta.json。
            # 全量爬取预约与课程管理前端的学期列表都依赖此文件，随日常爬取自愈。
            semester_meta = await self._extract_semesters(page)
            if semester_meta:
                self._save_course_meta(semester_meta)

            course_data = self._parse_course_table(html)

            # 验证数据类型
            if course_data is None:
                self.logger.error("课程表解析失败，未找到课程表数据")
                return None
            
            if not isinstance(course_data, dict):
                self.logger.error(f"课程表数据类型错误: {type(course_data)}")
                return None
            
            if 'headers' not in course_data or 'rows' not in course_data:
                self.logger.error("课程表数据结构不完整，缺少必要字段")
                return None
            
            self.logger.info(f"成功解析课程表，包含 {len(course_data['rows'])} 行数据")
            self.course_data = course_data
            self._save_raw_data(course_data, html)
            self.logger.info("课程表获取成功！")
            return course_data
            
        except Exception as e:
            self.logger.error(f"获取课程表时发生错误: {e}", exc_info=True)
            return None
            
        finally:
            # 确保浏览器和 playwright 都被正确关闭
            if browser:
                try:
                    await browser.close()
                    self.logger.debug("浏览器已关闭")
                except Exception as e:
                    self.logger.warning(f"关闭浏览器时出错: {e}")
            
            if playwright:
                try:
                    await playwright.stop()
                    self.logger.debug("Playwright 已停止")
                except Exception as e:
                    self.logger.warning(f"停止 Playwright 时出错: {e}")
    
    async def get_all_weeks_course_table(self, max_weeks=20, interactive=False):
        """
        获取所有周次的课程表
        
        支持两种模式：
        1. 自动模式（interactive=False）：程序自动切换周次
        2. 交互模式（interactive=True）：用户手动切换周次，按回车保存
        
        Args:
            max_weeks: 最大周次（默认20）
            interactive: 是否使用交互模式（默认False）
            
        Returns:
            dict: 包含所有周次课程数据的字典
        """
        if interactive:
            return await self._get_all_weeks_interactive(max_weeks)
        else:
            return await self._get_all_weeks_auto(max_weeks)
    
    async def _select_all_weeks(self, page):
        """
        在"选择教学周"下拉框中选择"全部"，触发整学期课表渲染。

        eams 中"全部"对应 startWeek 的空值（selectize 开启了 allowEmptyOption）。
        选择后调用 searchTable() 重新提交表单，后端返回整学期数据（每门课的
        TaskActivity 携带完整周次位图），而不是只返回当前周。

        Args:
            page: Playwright 页面对象

        Returns:
            bool: 是否成功触发（仅表示操作已执行，不代表数据已渲染完成）
        """
        self.logger.info("选择教学周：全部（获取整学期课表）")
        js = """
        () => {
            var select = document.getElementById('startWeek');
            if (!select) return 'no_select';
            var allVal = '';
            // 尝试从下拉选项中找到"全部"对应的真实 value
            try {
                var opts = select.options;
                for (var i = 0; i < opts.length; i++) {
                    if (opts[i].text && opts[i].text.indexOf('全部') !== -1) {
                        allVal = opts[i].value;
                        break;
                    }
                }
            } catch (e) {}
            // 通过 selectize API 或直设置底层 select
            if (select.selectize) {
                try { select.selectize.setValue(allVal); }
                catch (e) { select.value = allVal; }
            } else {
                select.value = allVal;
            }
            $(select).trigger('change');
            if (typeof searchTable === 'function') { searchTable(); }
            return 'ok:' + allVal;
        }
        """
        try:
            result = await page.evaluate(js)
            self.logger.info(f"选择'全部'执行结果: {result}")
        except Exception as e:
            self.logger.warning(f"选择'全部'执行异常: {e}")
            return False

        # 等待课表异步重新渲染（searchTable 提交到 contentDiv）
        await asyncio.sleep(6)

        # 弹窗已被注入脚本从源头废掉（alert 覆盖 + 自动移除 DOM），
        # 它不影响 searchTable 的提交与渲染，因此无需退避，直接继续。
        warning = await page.evaluate("""() => {
            var t = document.body.innerText;
            return (t.indexOf('过快') !== -1 || t.indexOf('不要频繁') !== -1);
        }""")
        if warning:
            self.logger.info("检测到'过快点击'提示（已被自动关闭，不影响渲染），继续解析...")

        return True

    async def _fetch_week_activities(self, page, week):
        """
        单独请求某一教学周的课表，返回解析后的 TaskActivity 列表。

        用于补充"全部"视图中可能漏渲染的周次（如最后几周）。每次请求间隔由
        调用方控制，内置"过快点击"检测与退避。

        Args:
            page: Playwright 页面
            week: 周次（1-20）

        Returns:
            tuple: (activities, unit_count)
        """
        js = f"""
        () => {{
            var select = document.getElementById('startWeek');
            if (!select) return 'no_select';
            if (select.selectize) {{
                try {{ select.selectize.setValue('{week}'); }}
                catch (e) {{ select.value = '{week}'; }}
            }} else {{
                select.value = '{week}';
            }}
            $(select).trigger('change');
            if (typeof searchTable === 'function') {{ searchTable(); }}
            return 'ok:{week}';
        }}
        """
        result = await page.evaluate(js)
        self.logger.info(f"补充请求第 {week} 周: {result}")
        await asyncio.sleep(8)

        # 弹窗已被注入脚本从源头废掉（不影响渲染），无需退避，直接轮询至稳定。
        prev = -1
        stable = 0
        html = ''
        for _ in range(20):
            await asyncio.sleep(1)
            html = await page.content()
            acts, _ = self._parse_activities(html)
            cnt = len(acts)
            if cnt == prev:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
                prev = cnt

        # 校验是否真的切换到了该单周（startWeek 值应为 week）。
        # 注意：eams 的"过快点击"只是视觉警告，**不阻断渲染**，且 selectize 的
        # value 在切换后未必立即等于 week（控件内部状态差异），因此这里**绝不 reload**
        # —— 重加载会把刚渲染好的单周数据又冲掉，且会陷入刷新循环。直接按已渲染
        # 的 TaskActivity 解析即可（弹窗已被注入脚本自动关闭）。
        selected = await page.evaluate(
            "() => { var s = document.getElementById('startWeek'); return s ? s.value : null; }"
        )
        if str(selected) != str(week):
            self.logger.warning(
                f"第 {week} 周 startWeek.value={selected!r}（与预期 {week} 不符），"
                f"但弹窗不影响渲染，直接按当前已渲染页面解析"
            )

        return self._parse_activities(html)

    async def _get_all_weeks_auto(self, max_weeks=20):
        """
        自动模式：单次加载课表页，显式选择教学周"全部"后解析页面 JavaScript 中的
        TaskActivity，一次即可得到整学期全部周次的课程安排。

        eams 页面加载后会自动提交表单渲染整学期课表，其 JS 里每门课的
        TaskActivity 都携带了整学期的周次位图。因此无需逐周切换（那样会频繁
        提交表单触发"过快点击"限流），只解析一次即可拿到全部数据。

        Args:
            max_weeks: 兼容旧接口的参数，本实现已不再逐周遍历，仅保留签名

        Returns:
            dict: 整学期课程数据 {headers, rows}，失败时返回 None
        """
        playwright = None
        browser = None
        
        try:
            playwright = await async_playwright().start()
            
            # 启动浏览器
            launch_options = {
                'headless': CONFIG['spider']['headless'],
                'args': [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-software-rasterizer',
                    '--disable-gpu'
                ]
            }
            
            browser = await playwright.chromium.launch(**launch_options)
            
            # 创建页面
            context_options = {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'locale': 'zh-CN',
                'timezone_id': 'Asia/Shanghai',
                'viewport': {'width': 1920, 'height': 1080},
                'color_scheme': 'light',
                'device_scale_factor': 1
            }
            
            context = await browser.new_context(**context_options)
            await context.add_init_script(_ANTI_THROTTLE_JS)
            page = await context.new_page()
            
            # 登录
            self.logger.info("正在登录...")
            if not await self._login(page):
                self.logger.error("登录失败")
                return None
            
            # 访问课表页面（带“过快点击/访问受限”检测与退避重试）
            self.logger.info("正在访问课表页面...")
            if not await self._goto_course_table(page):
                self.logger.error("进入课程页面失败，无法获取整学期课表")
                return None

            # 【学期切换】若指定了非当前学期，先切换再解析
            if self.semester_id:
                if not await self._switch_semester(page, self.semester_id):
                    self.logger.error("学期切换失败，无法获取目标学期课表")
                    return None

            # 页面加载后会自动提交表单渲染课表（默认当前周），等待其 JS（含 TaskActivity）就绪
            self.logger.info("等待初始课表加载...")
            html = ''
            for _ in range(20):
                await asyncio.sleep(1)
                html = await page.content()
                if 'TaskActivity' in html:
                    break
            
            # 缓冲：初始课表渲染完成后稍作等待，避免紧接着点"全部"被判定为"过快点击"
            self.logger.info("初始课表已加载，缓冲 10 秒后再选择'全部'...")
            await asyncio.sleep(10)

            # 【学期信息自动维护】整学期爬取同样加载课表页，顺手解析学期下拉写 course_meta.json。
            semester_meta = await self._extract_semesters(page)
            if semester_meta:
                self._save_course_meta(semester_meta)

            # 关键：显式选择教学周"全部"，触发整学期课表渲染
            # （默认仅渲染当前周，TaskActivity 只含该周课程；选"全部"后返回完整周次位图）
            await self._select_all_weeks(page)
            
            # 等待"全部"视图的课表重新渲染（searchTable 异步提交到 contentDiv）
            # 关键：eams 会分块异步注入课程单元格，必须等 TaskActivity 数量稳定后再解析，
            # 否则会漏掉最后渲染的周次（如第19周）导致整周课程缺失。
            self.logger.info("等待整学期课表渲染（轮询至 TaskActivity 数量稳定）...")
            # 等待「全部」视图的课表表格渲染完成。
            # 说明：教务系统服务器较慢时，课程单元格会分块异步注入；
            # 必须等表格内课程单元格数量稳定后再解析，否则会漏掉后渲染的周次。
            # （此前误以为「过快点击」弹窗会导致数据缺失，其实弹窗只是服务器慢、
            #  页面尚未渲染完的提示，点掉/等渲染即可，无需 reload 或切换周次。）
            self.logger.info("等待整学期课表表格渲染（轮询至课程单元格数量稳定）...")
            html = ''
            prev_cells = -1
            stable = 0
            course_table = None
            for _ in range(60):
                await asyncio.sleep(1)
                html = await page.content()
                soup = BeautifulSoup(html, 'html.parser')
                tables = soup.find_all('table')
                big = max(tables, key=lambda t: len(t.find_all('td'))) if tables else None
                cells = len(big.find_all('td')) if big else 0
                if cells > 30 and cells == prev_cells:
                    stable += 1
                    if stable >= 2:
                        course_table = big
                        break
                else:
                    stable = 0
                    prev_cells = cells
            if course_table is None:
                soup = BeautifulSoup(html, 'html.parser')
                tables = soup.find_all('table')
                course_table = max(tables, key=lambda t: len(t.find_all('td'))) if tables else None
                if course_table is not None:
                    self.logger.warning("课程单元格数量未完全稳定，使用当前已渲染表格（可能不完整）")

            if course_table is None:
                self.logger.error("未找到课程表，解析失败")
                return None

            # 【主数据源】直接由 TaskActivity 重建整学期结构化网格。
            # 说明：eams 页面 JS 中的 new TaskActivity(...) 数组携带每门课的
            #   整学期周次位图([6])、精确节次(slots)、教师、教室，是整学期权威源。
            # 相比解析「全部」视图的渲染表格（一格多课堆叠、易串味/错位），
            # 用 TaskActivity 重建的网格与处理层正则完全兼容（见 _build_grid_from_activities）。
            # 该数据不依赖「选全部」渲染是否成功，稳健性更好。
            self.logger.info("正在由 TaskActivity 重建整学期课程网格（权威数据源）...")
            acts, unit_count = [], 12
            try:
                acts, unit_count = self._parse_activities(html)
            except Exception:
                self.logger.warning("解析 TaskActivity 失败，将回退渲染表格")
            self.logger.info(f"从 TaskActivity 解析到 {len(acts)} 门课程（unit_count={unit_count}）")

            merged_data = None
            if acts:
                try:
                    merged_data = self._build_grid_from_activities(acts, unit_count)
                except Exception as e:
                    self.logger.warning(f"由 TaskActivity 重建网格失败: {e}，将回退渲染表格")
                    merged_data = None

            # 周次覆盖校验（非阻塞）：若 TaskActivity 未含整学期数据，则放弃并回退渲染表格。
            try:
                covered = self._count_distinct_weeks(acts)
                self.logger.info(f"解析覆盖的不同教学周数量: {covered}")
                if covered < 2:
                    self.logger.warning(
                        f"周次覆盖仅 {covered} 周，疑似 TaskActivity 未含整学期数据，"
                        f"将回退渲染表格解析"
                    )
                    merged_data = None
            except Exception:
                pass

            # 兜底：TaskActivity 失败或覆盖异常时，仍尝试解析「全部」视图渲染表格
            if not (merged_data and merged_data.get('rows')) and course_table is not None:
                self.logger.warning("回退：解析渲染表格（_extract_schedule）")
                try:
                    merged_data = self._extract_schedule(course_table.find_all('tr'))
                except Exception as e:
                    self.logger.warning(f"渲染表格解析也失败: {e}")

            if merged_data and merged_data.get('rows'):
                self._save_raw_data(merged_data, html, all_weeks=True)
                return merged_data
            else:
                self.logger.error("整学期课程数据解析失败（TaskActivity 与渲染表格均失败）")
                return None
            
        except Exception as e:
            self.logger.error(f"获取所有周次课程表时发生错误: {e}", exc_info=True)
            return None
            
        finally:
            # 关闭浏览器
            if browser:
                try:
                    await browser.close()
                    self.logger.debug("浏览器已关闭")
                except Exception as e:
                    self.logger.warning(f"关闭浏览器时出错: {e}")
            
            if playwright:
                try:
                    await playwright.stop()
                    self.logger.debug("Playwright 已停止")
                except Exception as e:
                    self.logger.warning(f"停止 Playwright 时出错: {e}")
    
    async def _get_all_weeks_interactive(self, max_weeks=20):
        """
        交互式获取所有周次的课程表
        
        登录后保持浏览器打开，用户手动切换周次，
        每切换完一个周次就在命令行按回车保存
        """
        playwright = None
        browser = None
        all_course_data = []
        
        try:
            playwright = await async_playwright().start()
            
            # 启动浏览器（使用非无头模式，让用户能看到）
            launch_options = {
                'headless': False,  # 强制使用有头模式
                'args': [
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-software-rasterizer',
                    '--disable-gpu'
                ]
            }
            
            browser = await playwright.chromium.launch(**launch_options)
            
            # 创建页面
            context_options = {
                'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'locale': 'zh-CN',
                'timezone_id': 'Asia/Shanghai',
                'viewport': {'width': 1920, 'height': 1080},
                'color_scheme': 'light',
                'device_scale_factor': 1
            }
            
            context = await browser.new_context(**context_options)
            page = await context.new_page()
            
            # 登录
            self.logger.info("=" * 60)
            self.logger.info("正在自动登录...")
            self.logger.info("=" * 60)
            
            if not await self._login(page):
                self.logger.error("登录失败")
                return None
            
            # 访问课表页面（带“过快点击/访问受限”检测与退避重试）
            self.logger.info("正在访问课表页面...")
            if not await self._goto_course_table(page):
                self.logger.error("进入课程页面失败，无法获取整学期课表")
                return None
            
            # 等待页面完全加载
            self.logger.info("等待页面初始化（15秒）...")
            await asyncio.sleep(15)
            
            self.logger.info("=" * 60)
            self.logger.info("【交互模式】登录成功！")
            self.logger.info("=" * 60)
            self.logger.info("现在你可以手动在浏览器中切换周次了")
            self.logger.info("操作步骤：")
            self.logger.info("  1. 在浏览器中找到'周次'下拉框")
            self.logger.info("  2. 选择一个周次（比如第1周）")
            self.logger.info("  3. 等待课表加载完成")
            self.logger.info("  4. 回到这个命令行窗口，按回车键")
            self.logger.info("  5. 程序会保存当前周次的课表")
            self.logger.info("  6. 重复步骤2-5，直到保存完所有需要的周次")
            self.logger.info("  7. 输入 'done' 完成并退出")
            self.logger.info("=" * 60)
            
            # 交互式循环
            week_count = 0
            while True:
                week_count += 1
                
                # 等待用户输入
                self.logger.info(f"\n[第 {week_count} 次保存]")
                self.logger.info("请先在浏览器中切换周次，然后按回车保存（或输入 'done' 完成）：")
                
                user_input = input("> ").strip().lower()
                
                if user_input == 'done':
                    self.logger.info("用户选择完成，退出交互模式")
                    break
                
                # 获取当前周次的值
                current_week = await page.evaluate("""
                () => {
                    var select = document.getElementById('startWeek');
                    return select ? select.value : null;
                }
                """)
                
                if not current_week:
                    self.logger.warning("未找到周次下拉框，跳过本次保存")
                    continue
                
                self.logger.info(f"正在保存第 {current_week} 周的课表...")
                
                # 获取HTML并解析
                html = await page.content()
                course_data = self._parse_course_table(html)
                
                if course_data:
                    course_data['week_number'] = int(current_week)
                    all_course_data.append(course_data)
                    self.logger.info(f"第 {current_week} 周数据保存成功，包含 {len(course_data.get('rows', []))} 行")
                else:
                    self.logger.warning(f"第 {current_week} 周数据解析失败")
                
                # 询问是否继续
                self.logger.info(f"已保存 {len(all_course_data)} 个周次的课表")
                
                # 自动检测是否已完成所有周次
                if len(all_course_data) >= max_weeks:
                    self.logger.info(f"已保存 {max_weeks} 个周次，自动完成")
                    break
            
            self.logger.info("=" * 60)
            self.logger.info(f"交互式采集完成，共保存 {len(all_course_data)} 个周次的课表")
            self.logger.info("=" * 60)
            
            # 合并所有周次的数据
            if all_course_data:
                merged_data = self._merge_all_weeks_data(all_course_data)
                self._save_raw_data(merged_data, None, all_weeks=True)
                return merged_data
            else:
                self.logger.error("没有成功保存任何周次的数据")
                return None
            
        except Exception as e:
            self.logger.error(f"交互式获取课程表时发生错误: {e}", exc_info=True)
            return None
            
        finally:
            # 关闭浏览器
            if browser:
                try:
                    self.logger.info("5秒后关闭浏览器...")
                    await asyncio.sleep(5)
                    await browser.close()
                    self.logger.debug("浏览器已关闭")
                except Exception as e:
                    self.logger.warning(f"关闭浏览器时出错: {e}")
            
            if playwright:
                try:
                    await playwright.stop()
                    self.logger.debug("Playwright 已停止")
                except Exception as e:
                    self.logger.warning(f"停止 Playwright 时出错: {e}")
    
    async def _select_week_and_wait(self, page, week):
        """
        选择周次并等待表格加载
        
        Args:
            page: Playwright页面对象
            week: 周次（1-20）
            
        Returns:
            bool: 选择成功返回True，否则返回False
        """
        try:
            # 使用JavaScript选择周次
            js_select = f"""
            () => {{
                var select = document.getElementById('startWeek');
                if (!select) return false;
                
                // 方法1: selectize API
                if (select.selectize) {{
                    select.selectize.setValue('{week}');
                    $(select).trigger('change');
                }} else {{
                    // 方法2: 直接设置
                    select.value = '{week}';
                    $(select).trigger('change');
                }}
                
                // 调用搜索函数
                if (typeof searchTable === 'function') {{
                    searchTable();
                }}
                
                return true;
            }}
            """
            
            result = await page.evaluate(js_select)
            
            if not result:
                self.logger.warning(f"第 {week} 周：未找到周次下拉框")
                return False
            
            # 等待表格重新加载
            self.logger.debug(f"等待第 {week} 周数据加载（8秒）...")
            await asyncio.sleep(8)
            
            # 检查是否有"过快点击"警告
            warning = await page.evaluate("""
            () => {{
                var text = document.body.innerText;
                if (text.includes('过快') || text.includes('不要频繁')) {{
                    return text.substring(0, 100);
                }}
                return null;
            }}
            """)
            
            if warning:
                # eams 的"过快点击"只是视觉警告，不阻断 searchTable 提交与渲染，
                # 弹窗已被注入脚本自动关闭。此处**绝不 reload**（否则会冲掉已渲染数据
                # 并陷入刷新循环），直接继续按已渲染页面解析即可。
                self.logger.warning(f"第 {week} 周触发'过快点击'提示（已被自动关闭，不影响渲染），继续...")
            
            # 验证选择是否成功
            selected = await page.evaluate("() => document.getElementById('startWeek').value")
            
            if selected == str(week):
                self.logger.debug(f"第 {week} 周选择成功")
                return True
            else:
                self.logger.warning(f"第 {week} 周选择失败，当前值: {selected}")
                return False
                
        except Exception as e:
            self.logger.error(f"选择第 {week} 周时发生错误: {e}")
            return False
    
    async def _extract_teacher_mapping_from_page(self, page):
        """
        从页面中提取教师姓名映射（通过执行JavaScript）
        
        在浏览器上下文中执行JavaScript，获取TaskActivity调用中的教师姓名
        
        Args:
            page: Playwright页面对象
            
        Returns:
            dict: 教师姓名映射，格式为 {课程代码: 教师姓名}
        """
        try:
            # 注入JavaScript代码来捕获教师姓名
            inject_js = """
            () => {
                // 创建一个全局变量来存储教师姓名映射
                window.teacherMapping = {};
                
                // 保存原始的TaskActivity构造函数（如果存在）
                if (typeof TaskActivity !== 'undefined') {
                    // TaskActivity可能是一个函数或构造函数
                    // 我们尝试重写它来捕获教师姓名
                    
                    // 但实际上，TaskActivity可能是在闭包中定义的，我们无法访问
                    // 所以我们需要直接解析页面中的JavaScript代码
                }
                
                // 直接解析页面中的script标签
                var scripts = document.querySelectorAll('script');
                for (var i = 0; i < scripts.length; i++) {
                    var scriptContent = scripts[i].textContent;
                    
                    // 查找所有的TaskActivity调用
                    var pattern = /new TaskActivity\\(([^)]+)\\)/g;
                    var match;
                    while ((match = pattern.exec(scriptContent)) !== null) {
                        var argsStr = match[1];
                        
                        // 解析参数（简化处理，假设参数格式固定）
                        // TaskActivity(teacherIds, teacherNames, courseCode, courseName, ...)
                        
                        // 使用正则表达式提取教师姓名和课程代码
                        var teacherNamesMatch = argsStr.match(/actTeacherName\\.join\\(['"]\\,['"]\\)/);
                        if (teacherNamesMatch) {
                            // 这是一个复杂的表达式，我们需要在页面的上下文中执行它
                            // 但这里我们无法执行，因为actTeacherName可能不在全局作用域
                            
                            // 让我们尝试一个更简单的方法：直接查找actTeacherName的定义
                        }
                        
                        // 查找actTeacherName变量
                        var namePattern = /actTeacherName\\s*=\\s*\\[([^\\]]+)\\]/;
                        var nameMatch = scriptContent.match(namePattern);
                        if (nameMatch) {
                            try {
                                // 执行这段代码来获取教师姓名数组
                                var teacherNames = eval('[' + nameMatch[1] + ']');
                                
                                // 查找对应的课程代码
                                // 课程代码在TaskActivity的第三个参数中
                                var args = argsStr.split(',');
                                if (args.length >= 3) {
                                    var courseCodeStr = args[2].trim().replace(/['"]/g, '');
                                    
                                    // 提取课程代码（去掉前面的数字）
                                    // "188444(220110460.02)" -> "220110460.02"
                                    var codeMatch = courseCodeStr.match(/\\(([^)]+)\\)/);
                                    if (codeMatch) {
                                        var courseCode = codeMatch[1];
                                        window.teacherMapping[courseCode] = teacherNames.join(',');
                                    }
                                }
                            } catch (e) {
                                console.error('Error parsing teacher names:', e);
                            }
                        }
                    }
                }
                
                return window.teacherMapping;
            }
            """
            
            teacher_mapping = await page.evaluate(inject_js)
            
            if teacher_mapping and len(teacher_mapping) > 0:
                self.logger.info(f"成功提取 {len(teacher_mapping)} 个教师姓名映射")
                return teacher_mapping
            else:
                self.logger.warning("未能提取教师姓名映射（JavaScript执行失败或页面格式不匹配）")
                return {}
                
        except Exception as e:
            self.logger.error(f"提取教师姓名映射时发生错误: {e}", exc_info=True)
            return {}
    
    def _extract_course_info(self, course_text, teacher_mapping=None):
        """
        从课程文本中提取课程信息
        
        格式示例：Vue.js前端框架应用(220110550.01) (罗强,罗明阳)\n([18]周,J060402机器学习技术实训室(校本部))
        格式示例：形势与政策 4(A01008008.98) (李亚腾)\n([12]周,J110301(校本部))
        格式示例：课程名(代码)\n([1-16]周,教室)  # 多周
        格式示例：课程名(代码)\n([2-5] [7-11单] [12-18]周,教室)  # 复杂周次
        
        Args:
            course_text: 课程文本
            teacher_mapping: 教师姓名映射（可选），格式为 {课程代码: 教师姓名}
        """
        if not course_text:
            return None
        
        # 定义匹配模式 - 支持复杂周次格式
        # 周次部分：捕获 [ 和 ]周 之间的所有内容（支持多个周次范围）
        pattern = r'^(.*?)\(([A-Za-z0-9]+\.[0-9]+)\)(?:\s*\(([^)]*)\))?\s*\(\[(.+?)\]周,(.*?)\(校本部\)\)'
        
        match = re.match(pattern, course_text, re.DOTALL)
        
        if not match:
            # 尝试不带"校本部"的格式
            pattern2 = r'^(.*?)\(([A-Za-z0-9]+\.[0-9]+)\)(?:\s*\(([^)]*)\))?\s*\(\[(.+?)\]周,(.*?)\)'
            match = re.match(pattern2, course_text, re.DOTALL)
        
        if not match:
            return None

        course_name = match.group(1).strip()
        course_code = match.group(2).strip()
        teacher = match.group(3).strip() if match.group(3) else ''
        weeks_str = match.group(4).strip()  # 可能是 "18" 或 "2-5 7-11单 12-18"
        classroom = match.group(5).strip()
        
        # 如果教师姓名为空，尝试从teacher_mapping中获取
        if not teacher and teacher_mapping and course_code in teacher_mapping:
            teacher = teacher_mapping[course_code]
        
        # 解析周次范围
        weeks_list = self._parse_weeks_string(weeks_str)
        
        return {
            'course_name': course_name,
            'course_code': course_code,
            'teacher': teacher,
            'weeks': weeks_str,  # 原始周次字符串
            'weeks_list': weeks_list,  # 解析后的周次列表
            'classroom': classroom,
            'week_number': weeks_list[0] if weeks_list else 1  # 提取第一个周数作为默认
        }
    
    def _merge_all_weeks_data(self, all_course_data):
        """
        合并所有周次的课程数据
        
        Args:
            all_course_data: 所有周次的课程数据列表
            
        Returns:
            dict: 合并后的课程数据
        """
        if not all_course_data:
            return None
        
        # 使用第一周的数据作为基础
        merged = {
            'headers': all_course_data[0].get('headers', []),
            'rows': [],
            'all_weeks': []
        }
        
        # 合并所有周次的行
        for week_data in all_course_data:
            week_number = week_data.get('week_number', 0)
            rows = week_data.get('rows', [])
            
            # 为每一行添加周次信息
            for row in rows:
                row_with_week = row + [f"第{week_number}周"]
                merged['rows'].append(row_with_week)
            
            merged['all_weeks'].append({
                'week_number': week_number,
                'row_count': len(rows)
            })
        
        return merged


def main():
    """主函数"""
    logger = get_logger('main')
    logger.info("=" * 60)
    logger.info("课程表爬虫与处理系统启动")
    logger.info("=" * 60)
    
    # 解析命令行参数
    import argparse
    parser = argparse.ArgumentParser(description='课程表爬虫与处理系统')
    parser.add_argument('--all-weeks', dest='all_weeks', action='store_true',
                        help='爬取所有周次（1-20周）')
    parser.add_argument('--interactive', dest='interactive', action='store_true',
                        help='交互模式：手动切换周次（需要 --all-weeks 参数）')
    parser.add_argument('--max-weeks', dest='max_weeks', type=int, default=20,
                        help='最大周次（默认20）')
    parser.add_argument('--semester-id', dest='semester_id', type=str, default=None,
                        help='指定学期ID（如 251=上学期2025-2026-1）。不指定则爬服务端默认（当前）学期')
    args, _ = parser.parse_known_args()
    
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        username = CONFIG['spider']['login']['username']
        password = CONFIG['spider']['login']['password']
        
        tool = CourseTableTool(username, password, semester_id=args.semester_id)
        if args.semester_id:
            logger.info(f"目标学期：semester.id={args.semester_id}（非当前学期，将执行学期切换）")
        else:
            logger.info("目标学期：服务端默认（当前）学期")
        
        # 设置超时时间（根据是否爬取所有周次调整）
        if args.all_weeks:
            if args.interactive:
                TIMEOUT_SECONDS = 3600  # 60分钟（交互模式，给用户充足时间）
                logger.info(f"将使用交互模式爬取所有周次（1-{args.max_weeks}周），请手动切换周次并按回车保存")
            else:
                TIMEOUT_SECONDS = 1800  # 30分钟（20周 × 90秒）
                logger.info(f"将自动爬取所有周次（1-{args.max_weeks}周），预计耗时约30分钟")
        else:
            TIMEOUT_SECONDS = 600  # 10分钟
        
        try:
            import asyncio
            
            # 创建超时任务
            if args.all_weeks:
                async def run_with_timeout():
                    return await tool.get_all_weeks_course_table(
                        max_weeks=args.max_weeks,
                        interactive=args.interactive
                    )
            else:
                async def run_with_timeout():
                    return await tool.get_course_table()
            
            # 使用 asyncio 的 timeout 功能
            course_data = asyncio.run(asyncio.wait_for(run_with_timeout(), timeout=TIMEOUT_SECONDS))
            
        except asyncio.TimeoutError:
            logger.error(f"[失败] 程序运行超时（超过{TIMEOUT_SECONDS}秒），程序将退出！")
            logger.error("[失败] 请检查网络连接或验证码识别是否正常，然后重新运行程序！")
            return 1
        
        if not course_data:
            logger.error("获取课程表失败！")
            return 1
        
        raw_data_dir = os.path.join(script_dir, CONFIG['processing']['raw_data_dir'])
        processed_data_dir = os.path.join(script_dir, CONFIG['processing']['processed_data_dir'])
        # 【学期隔离】指定学期时，原始与处理后数据均落到 semester_<id>/ 子目录
        if args.semester_id:
            raw_data_dir = os.path.join(raw_data_dir, f'semester_{args.semester_id}')
            processed_data_dir = os.path.join(processed_data_dir, f'semester_{args.semester_id}')

        # 传入内存中已爬取的 course_data，避免构造函数回退到读取扁平文件
        # raw/course_table.json（指定学期时原始数据落在 raw/semester_<id>/ 子目录，
        # 扁平路径不存在会导致 FileNotFoundError）。
        processor = CourseProcessor(course_data)
        processed_courses = processor.run(course_data, raw_data_dir, processed_data_dir)
        
        if not processed_courses:
            logger.error("处理课程数据失败！")
            return 1
        
        csv_files = [f for f in os.listdir(processed_data_dir) if f.endswith('.csv') and '_week' in f]
        if csv_files:
            csv_files.sort(key=lambda x: os.path.getmtime(os.path.join(processed_data_dir, x)), reverse=True)
            latest_csv = os.path.join(processed_data_dir, csv_files[0])
            
            # 可选：生成课程表图片
            if IMAGE_GEN_AVAILABLE:
                converter = CsvToImage(latest_csv)
                image_path = converter.run()
                
                if image_path:
                    logger.info(f"课程表图片生成成功: {image_path}")
                else:
                    logger.error("生成课程表图片失败！")
            else:
                logger.info("图片生成功能不可用，跳过")
        else:
            logger.warning("未找到处理后的CSV文件，跳过图片生成")
        
        logger.info("=" * 60)
        logger.info("所有任务完成！")
        logger.info("=" * 60)
        return 0
        
    except Exception as e:
        logger.error(f"主程序执行出错: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
