#!/usr/bin/env python3
"""
学生名单管理路由（/api/admin/roster/*）

管理端「学生名单」Tab 的后端：新建单个 / 批量导入（CSV、Excel）/
编辑 / 停用启用 / 删除 / 分页查询。
仅 @admin_required（与用户管理同级权限域）。
"""

import csv
import io

from flask import Blueprint, Response, request

from app.core.api_response import api_error, api_success
from app.core.logger import get_logger
from app.services.student_roster_service import StudentRosterService
from app.utils.auth_middleware import admin_required

logger = get_logger(__name__)

admin_roster_bp = Blueprint("admin_roster", __name__)

# 学校选项（小程序身份绑定可选列表；重庆科创职业学院必须保留，其余为模糊干扰项）
SCHOOL_OPTIONS = [
    "重庆科创职业学院",
    "重庆工程学院",
    "重庆大学",
    "西南大学",
    "重庆邮电大学",
    "重庆理工大学",
]

# 批量导入表头：兼容中英文列名
HEADER_MAP = {
    "school": "school",
    "学校": "school",
    "student_number": "student_number",
    "学号": "student_number",
    "class_name": "class_name",
    "班级": "class_name",
    "real_name": "real_name",
    "姓名": "real_name",
    "remark": "remark",
    "备注": "remark",
}


def _parse_upload_file(file_storage):
    """
    解析上传的名单文件（.csv / .xlsx），返回 list[dict]。
    表头：学校, 学号, 班级[, 姓名, 备注]（real_name/remark 可缺省）。
    """
    filename = (file_storage.filename or "").lower()
    raw = file_storage.read()
    if filename.endswith(".xlsx"):
        import openpyxl

        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        rows_iter = ws.iter_rows(values_only=True)
    else:
        # CSV：先试 utf-8-sig（兼容 Excel 另存的 BOM），再回退 gbk
        text = None
        for enc in ("utf-8-sig", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            raise ValueError("CSV 编码无法识别，请使用 UTF-8 或 GBK 编码保存")
        rows_iter = csv.reader(io.StringIO(text))

    rows = []
    for i, values in enumerate(rows_iter):
        values = ["" if v is None else str(v).strip() for v in values]
        if i == 0:
            header = [HEADER_MAP.get(h.strip().lower()) or HEADER_MAP.get(h.strip()) for h in values]
            continue
        if not any(values):
            continue
        item = {}
        for j, h in enumerate(header):
            if h:
                item[h] = values[j] if j < len(values) else ""
        rows.append(item)
    return rows


@admin_roster_bp.route("/students", methods=["GET"])
@admin_required
def list_students():
    """分页查询名单（可选：学校 / 关键字筛选）"""
    school = (request.args.get("school") or "").strip()
    keyword = (request.args.get("keyword") or "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(100, max(1, request.args.get("page_size", 20, type=int)))
    data = StudentRosterService.list(
        school=school or None,
        keyword=keyword or None,
        page=page,
        page_size=page_size,
    )
    return api_success(
        total=data["total"],
        items=data["items"],
        page=data["page"],
        page_size=data["page_size"],
    )


@admin_roster_bp.route("/students", methods=["POST"])
@admin_required
def create_student():
    """新建单个名单条目"""
    payload = request.get_json(silent=True) or {}
    row, err = StudentRosterService.create(
        school=payload.get("school"),
        student_number=payload.get("student_number"),
        class_name=payload.get("class_name"),
        real_name=payload.get("real_name"),
        remark=payload.get("remark"),
        is_active=payload.get("is_active", True),
    )
    if err:
        return api_error(message=err, http_status=400)
    return api_success(student=row.to_dict(), message="已添加")


@admin_roster_bp.route("/students/batch", methods=["POST"])
@admin_required
def batch_import():
    """批量导入（multipart/form-data，字段名 file，支持 .csv / .xlsx）"""
    if "file" not in request.files:
        return api_error(message="请上传名单文件", http_status=400)
    file_storage = request.files["file"]
    if not file_storage.filename:
        return api_error(message="文件名为空", http_status=400)
    try:
        rows = _parse_upload_file(file_storage)
    except ValueError as exc:
        return api_error(message=str(exc), http_status=400)
    except Exception as exc:
        logger.error(f"[StudentRoster] 解析上传文件失败: {exc}")
        return api_error(message="文件解析失败，请检查格式（表头：学校,学号,班级,姓名,备注）", http_status=400)
    if not rows:
        return api_error(message="文件中没有有效数据（需含表头 + 数据行）", http_status=400)
    result = StudentRosterService.create_batch(rows)
    return api_success(created=result["created"], failures=result["failures"])


@admin_roster_bp.route("/students/<int:roster_id>", methods=["PUT"])
@admin_required
def update_student(roster_id):
    """编辑名单条目（学校/学号只读，防止破坏绑定语义）"""
    payload = request.get_json(silent=True) or {}
    row, err = StudentRosterService.update(
        roster_id,
        class_name=payload.get("class_name"),
        real_name=payload.get("real_name"),
        remark=payload.get("remark"),
        is_active=payload.get("is_active"),
    )
    if not row:
        status = 404 if err and "不存在" in err else 400
        return api_error(message=err or "名单条目不存在", http_status=status)
    return api_success(student=row.to_dict(), message="已保存")


@admin_roster_bp.route("/students/<int:roster_id>", methods=["DELETE"])
@admin_required
def delete_student(roster_id):
    """删除名单条目"""
    ok = StudentRosterService.delete(roster_id)
    if not ok:
        return api_error(message="名单条目不存在", http_status=404)
    return api_success(message="已删除")


@admin_roster_bp.route("/schools", methods=["GET"])
@admin_required
def list_schools():
    """学校选项（管理端新建/筛选用，与小程序绑定页保持一致，顶层 schools 字段）"""
    return api_success(schools=SCHOOL_OPTIONS)


@admin_roster_bp.route("/template", methods=["GET"])
@admin_required
def download_template():
    """批量导入 CSV 模板下载"""
    content = "学校,学号,班级,姓名,备注\n重庆科创职业学院,20260001,计算机2301,张三,\n"
    return Response(
        content.encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="student_roster_template.csv"'},
    )
