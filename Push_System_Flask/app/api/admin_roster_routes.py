#!/usr/bin/env python3
"""
学生名单管理路由（/api/admin/roster/*）

管理端「学生身份」Tab 的后端：组织树（学校/学院/专业/班级）维护 +
学生名单 CRUD + 一次性绑定码发放 + 批量导入（CSV、Excel）+ 分页查询。
仅 @admin_required（与用户管理同级权限域）。

组织维度（v6.17）：学校选项不再硬编码，改为从组织树动态读取；
名单录入只选班级节点，学校/学院/专业/班级名由树继承，不再逐行重复填写。
"""

import csv
import io

from flask import Blueprint, Response, request

from app.core.api_response import api_error, api_success
from app.core.logger import get_logger
from app.services.org_unit_service import OrgUnitService
from app.services.student_roster_service import StudentRosterService
from app.utils.auth_middleware import admin_required

logger = get_logger(__name__)

admin_roster_bp = Blueprint("admin_roster", __name__)

# 批量导入表头：兼容中英文列名（班级定位用名称路径，组织须先建好）
HEADER_MAP = {
    "school": "school",
    "学校": "school",
    "student_number": "student_number",
    "学号": "student_number",
    "class_name": "class_name",
    "班级": "class_name",
    "college": "college",
    "学院": "college",
    "major": "major",
    "专业": "major",
    "real_name": "real_name",
    "姓名": "real_name",
    "remark": "remark",
    "备注": "remark",
}


def _parse_upload_file(file_storage):
    """
    解析上传的名单文件（.csv / .xlsx），返回 list[dict]。
    表头：学校, 学院, 专业, 班级, 学号[, 姓名, 备注]（姓名/备注可缺省；
    学院/专业/班级须与已建组织节点名称一致，用于定位班级）。
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


# ==================== 组织树（学校/学院/专业/班级） ====================


@admin_roster_bp.route("/org/tree", methods=["GET"])
@admin_required
def org_tree():
    """组织树（顶层为学校，含 children），供管理端组织管理 + 名单录入级联选择"""
    return api_success(tree=OrgUnitService.tree())


@admin_roster_bp.route("/org", methods=["POST"])
@admin_required
def org_create():
    """新建组织节点：{node_type: school|college|major|class, name, parent_id?}"""
    payload = request.get_json(silent=True) or {}
    unit, err = OrgUnitService.create(
        node_type=payload.get("node_type"),
        name=payload.get("name"),
        parent_id=payload.get("parent_id"),
    )
    if err:
        return api_error(message=err, http_status=400)
    return api_success(unit=unit.to_dict(), message="已创建")


@admin_roster_bp.route("/org/<int:unit_id>", methods=["PUT"])
@admin_required
def org_rename(unit_id):
    """重命名组织节点（同级查重 + 级联刷新子树名单冗余路径名）"""
    payload = request.get_json(silent=True) or {}
    unit, err = OrgUnitService.rename(unit_id, name=payload.get("name"))
    if not unit:
        status = 404 if err and "不存在" in err else 400
        return api_error(message=err or "节点不存在", http_status=status)
    return api_success(unit=unit.to_dict(), message="已保存")


@admin_roster_bp.route("/org/<int:unit_id>", methods=["DELETE"])
@admin_required
def org_delete(unit_id):
    """删除组织节点（有子节点或被名单引用时拒绝）"""
    ok, err = OrgUnitService.delete(unit_id)
    if not ok:
        return api_error(message=err or "节点不存在", http_status=400)
    return api_success(message="已删除")


# ==================== 学生名单 ====================


@admin_roster_bp.route("/students", methods=["GET"])
@admin_required
def list_students():
    """分页查询名单（可选：学校 / 班级节点 class_id / 关键字筛选）"""
    school = (request.args.get("school") or "").strip()
    class_id = request.args.get("class_id", type=int) or None
    keyword = (request.args.get("keyword") or "").strip()
    page = max(1, request.args.get("page", 1, type=int))
    page_size = min(100, max(1, request.args.get("page_size", 20, type=int)))
    data = StudentRosterService.list(
        school=school or None,
        class_id=class_id,
        keyword=keyword or None,
        page=page,
        page_size=page_size,
    )
    # 注意：前端 UserManagementRoster.load() 读取 res.data / res.total（与 ApiResponse<RosterStudent[]> 契约一致），
    # 因此列表数据必须放在 data 字段（api_success 的 **extra 路径不会生成 data），否则列表恒为空。
    return api_success(
        data=data["items"],
        total=data["total"],
        page=data["page"],
        page_size=data["page_size"],
    )


@admin_roster_bp.route("/students/export", methods=["GET"])
@admin_required
def export_students():
    """导出名单 CSV（按当前筛选 school / class_id / keyword 全量导出，不分页）。

    列顺序与前端表格展示一致：学号、姓名、学校、学院、专业、班级、状态、备注、
    是否已发码、绑定用户名、绑定时间、创建时间。csv 模块负责引号/逗号/换行转义。
    """
    school = (request.args.get("school") or "").strip() or None
    class_id = request.args.get("class_id", type=int) or None
    keyword = (request.args.get("keyword") or "").strip() or None

    items = StudentRosterService.export(school=school, class_id=class_id, keyword=keyword)

    buf = io.StringIO()
    # utf-8-sig 让 Excel 直接打开中文不乱码；csv 引用器自动处理逗号/换行/引号
    writer = csv.writer(buf)
    writer.writerow(
        [
            "学号",
            "姓名",
            "学校",
            "学院",
            "专业",
            "班级",
            "状态",
            "备注",
            "是否已发码",
            "绑定用户名",
            "绑定时间",
            "创建时间",
        ]
    )
    for it in items:
        writer.writerow(
            [
                it.get("student_number") or "",
                it.get("real_name") or "",
                it.get("school") or "",
                it.get("college") or "",
                it.get("major") or "",
                it.get("class_name") or "",
                "启用" if it.get("is_active") else "停用",
                it.get("remark") or "",
                "是" if it.get("has_bind_code") else "否",
                it.get("bound_username") or "",
                (it.get("bound_at") or "").replace("T", " ")[:19],
                (it.get("created_at") or "").replace("T", " ")[:19],
            ]
        )

    # 文件名带筛选条件与时间戳，便于多次导出区分
    from datetime import datetime as _dt

    suffix_parts = [school or "全部学校", class_id and f"class_{class_id}" or None]
    suffix = "_".join(p for p in suffix_parts if p)
    filename = f"学生名单_{suffix}_{_dt.now().strftime('%Y%m%d_%H%M%S')}.csv"

    return Response(
        buf.getvalue().encode("utf-8-sig"),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@admin_roster_bp.route("/students", methods=["POST"])
@admin_required
def create_student():
    """按班级节点新建名单条目（组织名由树继承）"""
    payload = request.get_json(silent=True) or {}
    row, err = StudentRosterService.create(
        class_id=payload.get("class_id"),
        student_number=payload.get("student_number"),
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
        return api_error(message="文件解析失败，请检查格式（表头：学校,学院,专业,班级,学号,姓名,备注）", http_status=400)
    if not rows:
        return api_error(message="文件中没有有效数据（需含表头 + 数据行）", http_status=400)
    result = StudentRosterService.create_batch(rows)
    return api_success(created=result["created"], failures=result["failures"])


@admin_roster_bp.route("/students/<int:roster_id>", methods=["PUT"])
@admin_required
def update_student(roster_id):
    """编辑名单条目（学校/学号只读，防止破坏绑定语义；班级可换）"""
    payload = request.get_json(silent=True) or {}
    row, err = StudentRosterService.update(
        roster_id,
        class_id=payload.get("class_id"),
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


# ==================== 一次性绑定码 ====================


@admin_roster_bp.route("/students/<int:roster_id>/bind-code", methods=["POST"])
@admin_required
def generate_student_code(roster_id):
    """为学生生成一次性绑定码（覆盖旧码即旧码作废），明文仅本次返回"""
    code, err = StudentRosterService.generate_bind_code(roster_id)
    if err:
        return api_error(message=err, http_status=400)
    # data 包裹：前端统一从 res.data 取值
    return api_success(data={"code": code}, message="生成成功，请立即复制并私下发放")


@admin_roster_bp.route("/students/bind-codes", methods=["POST"])
@admin_required
def generate_student_codes_batch():
    """批量生成绑定码（{ids:[...]}），返回明文列表供导出 CSV 一次性发放"""
    payload = request.get_json(silent=True) or {}
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not ids:
        return api_error(message="请选择要生成绑定码的学生", http_status=400)
    codes = StudentRosterService.generate_bind_codes(ids)
    return api_success(data={"codes": codes, "count": len(codes)})


# ==================== 学校选项（动态）与模板 ====================


@admin_roster_bp.route("/schools", methods=["GET"])
@admin_required
def list_schools():
    """学校选项（从组织树动态读取，与小程序绑定页保持一致，顶层 schools 字段）"""
    units = OrgUnitService.list_schools()
    return api_success(schools=[u["name"] for u in units])


@admin_roster_bp.route("/template", methods=["GET"])
@admin_required
def download_template():
    """批量导入 CSV 模板下载（组织名须与已建节点一致）"""
    content = (
        "学校,学院,专业,班级,学号,姓名,备注\n"
        "重庆科创职业学院,信息与人工智能学院,计算机应用技术,zk2401,20260001,张三,\n"
    )
    return Response(
        content.encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": 'attachment; filename="student_roster_template.csv"'},
    )
