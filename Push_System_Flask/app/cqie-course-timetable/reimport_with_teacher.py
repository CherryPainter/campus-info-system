# -*- coding: utf-8 -*-
"""
离线重处理：从已保存的 course_table.html 重建课表，
用源 HTML 解析出的教师映射（非写死）补全教师，并重新入库。

用法：在 app/cqie-course-timetable 目录下运行
"""
import sys, os, json, re, datetime
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
# Flask 项目根目录（app 包所在位置）
sys.path.insert(0, os.path.abspath(os.path.join(_HERE, '..', '..')))

from bs4 import BeautifulSoup
from course_processing.process_course_data import (
    CourseProcessor, extract_teacher_map_from_html
)

RAW_HTML = 'output/course-data/raw/course_table.html'
PROCESSED_DIR = 'output/course-data/processed'

# 1. 读取源 HTML
with open(RAW_HTML, 'r', encoding='utf-8') as f:
    html = f.read()

# 2. 从源 HTML 实时解析教师映射（非写死）
teacher_map = extract_teacher_map_from_html(html)
print(f'[1] 从源 HTML 解析到 {len(teacher_map)} 条课程代码->教师映射')

# 3. 解析渲染表格为 {headers, rows}（含 rowspan 跨节处理）
soup = BeautifulSoup(html, 'html.parser')
table = soup.find('table')
if not table:
    print('ERROR: 未找到表格')
    sys.exit(1)

day_names = ['星期一', '星期二', '星期三', '星期四', '星期五', '星期六', '星期日']
headers = ['节次/周次'] + day_names

rows_data = []
rowspan_tracker = {}

for row in table.find_all(['tr']):
    cells = row.find_all(['td', 'th'])
    ft = cells[0].get_text(strip=True) if cells else ''
    if '打印预览' in ft or len(ft) > 20:
        continue
    if ft == '节次/周次' and len(cells) > 8:
        continue

    rd = []
    ci = 0
    for cell in cells:
        while ci in rowspan_tracker:
            cnt, rem = rowspan_tracker[ci]
            rd.append(cnt)
            if rem > 1:
                rowspan_tracker[ci] = (cnt, rem - 1)
            else:
                del rowspan_tracker[ci]
            ci += 1
        ct = cell.get_text(strip=True)
        rs = int(cell.get('rowspan', 1))
        if rs > 1:
            rowspan_tracker[ci] = (ct, rs - 1)
        rd.append(ct)
        ci += 1
    while ci in rowspan_tracker:
        cnt, rem = rowspan_tracker[ci]
        rd.append(cnt)
        if rem > 1:
            rowspan_tracker[ci] = (cnt, rem - 1)
        else:
            del rowspan_tracker[ci]
        ci += 1
    rows_data.append(rd)

course_data = {'headers': headers, 'rows': rows_data}
print(f'[2] 提取渲染表格行数: {len(rows_data)}')

# 4. 处理（传入教师映射）
processor = CourseProcessor(course_data=course_data, teacher_map=teacher_map)
processor.run(course_data=course_data, processed_dir=PROCESSED_DIR)

fc = processor.final_courses
print(f'[3] final_courses: {len(fc)} 门')

# 5. 统计教师填充情况
with_teacher = sum(1 for c in fc if c.get('teacher'))
print(f'    含教师的课程: {with_teacher}/{len(fc)}')

# 6. 重新入库（软删旧 + 插新）
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '.env'))

from app import create_app
from app.model.course import Course
from app.repository.course_repository import CourseRepository
from app.core.database import get_db

app = create_app()
with app.app_context():
    session = get_db()

    old_count = session.query(Course).filter(Course.is_deleted == False).count()
    if old_count > 0:
        session.query(Course).filter(Course.is_deleted == False).update({
            'is_deleted': True,
            'deleted_at': datetime.datetime.now(),
            'deleted_reason': 'Re-import: fill teacher from source HTML (not hardcoded)'
        })
        session.commit()
        print(f'[4] 软删除旧数据 {old_count} 门')

    dm = {'星期一': 1, '星期二': 2, '星期三': 3, '星期四': 4, '星期五': 5, '星期六': 6, '星期日': 7}
    cn_num_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}

    def parse_cn(s):
        if s in cn_num_map:
            return cn_num_map[s]
        try:
            return int(s)
        except Exception:
            return 0

    transformed = []
    for c in fc:
        wd = c.get('week_day', '')
        day_int = dm.get(wd)
        if day_int is None:
            try:
                day_int = int(wd)
            except Exception:
                day_int = 1

        pname = c.get('period_name', '')
        periods = c.get('periods', [])
        pidx = c.get('period_idx', 1)

        if not periods and pname:
            m = re.match(r'第([一二三四五六七八九十\d]+)、([一二三四五六七八九十\d]+)节', pname)
            if m:
                f, s2 = parse_cn(m.group(1)), parse_cn(m.group(2))
                if f > 0 and s2 > 0 and f <= s2:
                    periods = list(range(f, s2 + 1))
                    pidx = f
            else:
                sm = re.match(r'第([一二三四五六七八九十\d]+)节', pname)
                if sm:
                    pidx = parse_cn(sm.group(1))
                    periods = [pidx] if pidx > 0 else []

        if not periods and pidx > 0:
            periods = [pidx]

        wv = c.get('weeks_list', c.get('weeks'))
        weeks_str = json.dumps(wv) if isinstance(wv, list) else str(wv) if wv else ''

        transformed.append({
            'course_code': c.get('course_code'),
            'course_name': c.get('course_name', ''),
            'teacher': c.get('teacher', ''),
            'classroom': c.get('classroom', ''),
            'building': c.get('building', ''),
            'week_day': day_int,
            'period_idx': pidx,
            'periods': periods,
            'start_time': c.get('start_time', ''),
            'end_time': c.get('end_time', ''),
            'weeks': weeks_str,
            'week_number': c.get('week_number'),
        })

    count = CourseRepository.create_batch(session, transformed)
    session.commit()

    new_total = session.query(Course).filter(Course.is_deleted == False).count()
    print(f'[5] 入库完成: 新增 {count} 门, 当前有效 {new_total} 门')

    # 验证教师填充
    with_t = session.query(Course).filter(
        Course.is_deleted == False,
        Course.teacher != '',
        Course.teacher.isnot(None)
    ).count()
    print(f'    含教师的记录: {with_t}/{new_total}')
