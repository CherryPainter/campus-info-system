#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
课程爬取预约任务服务层

负责：
- 创建 / 校验爬取预约任务（范围：指定学期 / 全量；方式：立即 / 预约）
- 实际执行爬虫并将处理后的数据导入数据库（带学期打签）
- 被 APScheduler 调度器定时扫描（dispatch_scheduled_crawls）拾取到期任务

设计要点：
- 立即执行的任务在创建时由调用方直接起线程跑（响应快）；
- 预约任务由调度器在 scheduled_at 到达后拾取执行；
- 调度器同时作为「立即任务兜底」：若某立即任务创建超过 60 秒仍未 running，
  说明创建时的线程未启动（如刚重启），调度器会补跑，避免任务卡死。
"""
import os
import sys
import json
from datetime import datetime, timedelta

from app.core.logger import get_logger
from app.repository.course_repository import derive_current_semester
from app.core.task_state import TaskStatus
from app.services.spider_runner import run_spider_process

logger = get_logger(__name__)


# ----------------------------------------------------------------------
# 学期解析辅助
# ----------------------------------------------------------------------
def _read_course_meta():
    """读取爬虫保存的 course_meta.json，返回 dict 或 None。"""
    meta_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        'app', 'cqie-course-timetable', 'output', 'course-data', 'raw', 'course_meta.json'
    )
    if not os.path.exists(meta_path):
        return None
    try:
        with open(meta_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f'[爬取任务] 读取 course_meta.json 失败: {e}')
        return None


def _semester_name_to_id(name: str):
    """将学期名称（如 '2025-2026-1'）转换为 DB 格式 semester_id（20251）。"""
    try:
        parts = name.split('-')
        year = int(parts[0])
        term = int(parts[-1])
        return year * 10 + term
    except (ValueError, IndexError, AttributeError):
        return None


def _resolve_eams_id(semester_id: int):
    """根据 DB 格式 semester_id 反查教务系统内部学期 id（如 20251 -> '251'）。

    course_meta.json 缺失（首次部署/爬虫尚未成功）时，用 DB id 末三位直接
    推断 eams id（20252 -> '252'），使指定学期爬取在无元数据时也能工作。
    """
    meta = _read_course_meta()
    if not meta:
        return str(semester_id)[-3:]
    for s in meta.get('semesters', []):
        if _semester_name_to_id(s.get('name', '')) == semester_id:
            return str(s.get('id'))
    return str(semester_id)[-3:]


def _all_semester_pairs():
    """返回 [(eams_id, db_semester_id), ...]，来源于 course_meta.json。

    course_meta.json 缺失（首次部署/爬虫尚未成功）时，回退到按当前日期推导的
    学期，使全量爬取能直接爬取本学期，打破「没有 course_meta 就无法爬取、
    爬取不了就永远没有 course_meta」的死结。
    """
    meta = _read_course_meta()
    if not meta:
        db_id = derive_current_semester()['semester_id']
        return [(str(db_id)[-3:], db_id)]
    pairs = []
    for s in meta.get('semesters', []):
        eid = str(s.get('id'))
        db_id = _semester_name_to_id(s.get('name', ''))
        if eid and db_id:
            pairs.append((eid, db_id))
    return pairs


# ----------------------------------------------------------------------
# 爬虫执行
# ----------------------------------------------------------------------
def _python_command():
    from app.utils.platform_utils import PlatformUtils
    return os.environ.get('PYTHON_PATH', '') or PlatformUtils.get_python_command()


def _crawl_one_semester(eams_id: str, semester_id: int, week: int = None, timeout: int = 900, scope_label: str = None):
    """
    爬取单个学期并导入数据库。

    Args:
        eams_id: 教务系统内部学期 id（如 '251'）
        semester_id: DB 格式学期 id（如 20251），用于数据打签
        week: 可选指定周次；None 表示整学期
        timeout: 单学期爬虫超时（秒）
        scope_label: 可选，透传给 pipeline.save_to_database 用于进程名称区分
                     （全量爬取各学期传 '全部学期'；指定学期留空由 semester_id 决定）

    Returns:
        Tuple[int, int]: (新建课程数, 更新课程数)。导入失败时抛 RuntimeError。
    """
    from app.core.config import Config
    spider_dir = os.path.join(Config.BASE_DIR, 'app', 'cqie-course-timetable')
    script = os.path.join(spider_dir, 'main.py')
    if not os.path.exists(script):
        raise FileNotFoundError(f'爬虫脚本不存在: {script}')

    cmd = ['--semester-id', str(eams_id)]
    if week:
        # 指定单周：透传 --week（注意 main.py argparse 未定义 --week 时会被忽略，
        # 仅整学期路径是关键）
        cmd.extend(['--week', str(week)])
    else:
        # 整学期爬取：必须加 --all-weeks，否则 main() 走 get_course_table()
        # 只抓服务端默认渲染的「当前周」，导致「切换周次为全部再解析」的逻辑
        # （_get_all_weeks_auto → _select_all_weeks）根本不会被调用，每学期只拿到一个周次。
        cmd.append('--all-weeks')

    logger.info(f'[爬取任务] 开始爬取学期 eams_id={eams_id} (DB={semester_id})，命令参数: {cmd}')
    result = run_spider_process(cmd, timeout=timeout)
    if result.returncode != 0:
        tail = (result.stderr or result.stdout or '')[-500:]
        raise RuntimeError(f'爬虫执行失败 (code={result.returncode}): {tail}')

    # 导入：指定学期数据落在 processed/semester_<eams_id>/ 子目录
    processed_subdir = os.path.join(spider_dir, 'output', 'course-data', 'processed', f'semester_{eams_id}')
    if not os.path.isdir(processed_subdir):
        # 兜底：退回到基础 processed 目录
        processed_subdir = os.path.join(spider_dir, 'output', 'course-data', 'processed')

    sys.path.insert(0, spider_dir)
    import importlib
    pipeline = importlib.import_module('pipeline')
    created, updated = pipeline.save_to_database(
        processed_subdir, logger, semester_id=semester_id, scope_label=scope_label,
        data_source='full'
    )
    if created < 0:
        raise RuntimeError(f'学期 {eams_id} 数据导入失败')
    if created == 0 and updated == 0:
        # 真·无数据：本次既无新增也无更新，学期可能确无排课（或爬虫解析退化，已由空结果护栏另行告警）
        logger.warning(f'[爬取任务] 学期 {eams_id} 未导入任何课程（可能无排课数据）')
    elif created == 0:
        # 重爬已存在课程：全部命中 update 分支、新建数为 0，但已有数据已刷新，属正常，不告警
        logger.info(f'[爬取任务] 学期 {eams_id} 重爬刷新完成（新增 0 条 / 更新 {updated} 条），属正常')
    else:
        logger.info(f'[爬取任务] 学期 {eams_id} 成功导入 {created} 门课程（更新 {updated} 条）')
    logger.info(f'[爬取任务] 学期 eams_id={eams_id} 爬取+导入完成')
    return created, updated


def _crawl_all_semesters(timeout: int = 900):
    """全量爬取：遍历 course_meta.json 中所有学期，逐个爬取并导入。

    单个学期失败不中断整体，记录失败列表后继续，最后汇总。
    """
    pairs = _all_semester_pairs()
    if not pairs:
        raise RuntimeError('未找到任何学期配置（course_meta.json 为空或缺失）')
    logger.info(f'[爬取任务] 全量爬取开始，共 {len(pairs)} 个学期')
    failed = []
    total_imported = 0
    for idx, (eid, db_id) in enumerate(pairs, 1):
        logger.info(f'[爬取任务] 全量进度 {idx}/{len(pairs)}：学期 {eid}')
        try:
            created, updated = _crawl_one_semester(eid, db_id, week=None, timeout=timeout, scope_label='全部学期')
            if created > 0:
                total_imported += created
        except Exception as e:
            logger.error(f'[爬取任务] 学期 {eid} 爬取失败，跳过继续: {e}')
            failed.append((eid, str(e)[:200]))
    if failed:
        summary = '；'.join(f'{eid}:{msg}' for eid, msg in failed)
        logger.warning(f'[爬取任务] 全量爬取完成，{len(failed)} 个学期失败: {summary}')
        # 仅当全部失败时抛错，部分失败视为成功（已导入其余学期）
        if len(failed) == len(pairs):
            raise RuntimeError(f'全部学期爬取失败: {summary}')
    return total_imported


# ----------------------------------------------------------------------
# 任务执行入口（被线程 / 调度器调用）
# ----------------------------------------------------------------------
def _run_scheduled_crawl(task_id: int):
    """执行单个预约爬取任务，更新其状态。"""
    from app.core.database import get_db
    from app.model.scheduled_crawl_task import ScheduledCrawlTask
    from app.api.process_routes import create_task_process, complete_task_process

    session = get_db()
    try:
        task = session.query(ScheduledCrawlTask).filter(ScheduledCrawlTask.id == task_id).first()
        if not task:
            logger.warning(f'[爬取任务] 任务不存在: id={task_id}')
            return
        if task.status != TaskStatus.PENDING:
            logger.info(f'[爬取任务] 任务 {task_id} 状态为 {task.status}，跳过执行')
            return

        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now()
        task.message = '爬取任务执行中...'
        session.commit()

        # 统一「伞进程」：与「进程管理」页面同一套机制，前端任务卡片（full_crawl）
        # 据此感知真实的「运行中 / 成功 / 失败」终态，不再依赖 spider_status 的
        # running_tasks.course_full_crawl 或 crawlTasks.list 轮询。
        # 注：pipeline.save_to_database 仍会按学期各生成一条带后缀的明细进程
        # （课程全量爬取·学期X），本伞进程代表整次爬取任务，二者互补，互不冲突。
        process_id = None
        try:
            process_id = create_task_process(
                '课程全量爬取', 'course_full_crawl', total_items=1,
                created_by=task.created_by or 'admin',
            )
        except Exception as pe:
            logger.warning(f'[爬取任务] 创建伞进程失败（不影响爬取）: {pe}')

        try:
            if task.scope == 'all':
                total = _crawl_all_semesters()
            else:
                # 指定学期
                eams_id = task.eams_id or _resolve_eams_id(task.semester_id)
                if not eams_id:
                    raise RuntimeError(f'无法解析学期 eams_id（semester_id={task.semester_id}）')
                created, updated = _crawl_one_semester(eams_id, task.semester_id, week=task.week)
                total = created + updated  # 总处理条数（新增 + 更新）
            if total and total > 0:
                task.status = TaskStatus.COMPLETED
                if created > 0:
                    task.message = f'爬取完成，成功导入 {created} 门课程（更新 {updated} 条）'
                else:
                    # 重爬已存在课程：无新增、全部为更新，属正常，不报空
                    task.message = f'爬取完成，重爬刷新 {updated} 门课程（新增 0 条），属正常'
                if process_id is not None:
                    complete_task_process(process_id, TaskStatus.COMPLETED, task.message)
            else:
                task.status = TaskStatus.COMPLETED_EMPTY
                task.message = '爬取流程已正常完成，但未获取到任何课程数据（该学期可能尚未排课，或爬虫未能匹配到数据，请确认后重试）'
                if process_id is not None:
                    complete_task_process(process_id, TaskStatus.COMPLETED_EMPTY, task.message)
        except Exception as e:
            logger.error(f'[爬取任务] 任务 {task_id} 执行失败: {e}')
            task.status = TaskStatus.FAILED
            task.error_message = str(e)[:500]
            if process_id is not None:
                complete_task_process(process_id, TaskStatus.FAILED, error=str(e)[:500])
        finally:
            task.completed_at = datetime.now()
            session.commit()
    finally:
        session.close()


# 僵尸任务自愈阈值（秒）：running/pending 超过此时长仍未终结，视为进程被杀或线程中断
# 留下的僵尸任务，自动翻 failed。取值需大于任何单次爬取的最大可能耗时
# （全量遍历多学期约十几分钟），此处取 30 分钟，确保不会误杀真正在跑的任务。
STALE_TASK_THRESHOLD_SECONDS = 30 * 60


def reap_stale_crawl_tasks(session=None) -> int:
    """僵尸任务自愈：把长时间卡在 running/pending 的任务翻成 failed。

    根因：_run_scheduled_crawl 虽有 try/except/finally 翻状态，但若进程被杀
    （如爬取途中重启 Flask）或线程被强制终止，finally 不执行 → 任务永久 running，
    导致前端「任务运行中，自动刷新...」横幅永不熄灭。此函数由调度器每 30s 调用，
    以 started_at（无则 created_at）判断运行时长，超阈值即自动失败，打破死锁。

    Returns: 本次自愈（翻 failed）的任务数量。
    """
    from app.core.database import get_db
    from app.model.scheduled_crawl_task import ScheduledCrawlTask
    from app.model.task_process import TaskProcess
    from app.api.process_routes import complete_task_process

    own_session = session is None
    if own_session:
        session = get_db()
    reaped = 0
    try:
        now = datetime.now()
        deadline = now - timedelta(seconds=STALE_TASK_THRESHOLD_SECONDS)
        stale = session.query(ScheduledCrawlTask).filter(
            ScheduledCrawlTask.status.in_([TaskStatus.RUNNING, TaskStatus.PENDING])
        ).all()
        for t in stale:
            # 运行/等待起点：running 用 started_at，pending 用 created_at
            ref_time = t.started_at if (t.status == TaskStatus.RUNNING and t.started_at) else t.created_at
            if ref_time and ref_time < deadline:
                t.status = TaskStatus.FAILED
                t.error_message = (
                    f'任务超过 {STALE_TASK_THRESHOLD_SECONDS // 60} 分钟未完成，'
                    f'疑似进程中断/被杀，已自动标记失败（僵尸任务自愈）'
                )
                t.completed_at = now
                reaped += 1
                logger.warning(f'[爬取任务] 僵尸自愈：任务 id={t.id} 运行超时，自动翻 failed')
                # 同步结束对应的伞进程（课程全量爬取），避免前端「运行中」横幅永不熄灭。
                # 因 ScheduledCrawlTask 未持有 process_id（避免改表），按
                # 名称+类型+运行时长匹配仍 running/pending 的伞进程一并翻 failed。
                try:
                    running_procs = session.query(TaskProcess).filter(
                        TaskProcess.name == '课程全量爬取',
                        TaskProcess.task_type == 'course_full_crawl',
                        TaskProcess.status.in_(['running', 'pending']),
                    ).all()
                    for p in running_procs:
                        if p.started_at and p.started_at < deadline:
                            complete_task_process(p.id, TaskStatus.FAILED, error=t.error_message)
                except Exception as pe:
                    logger.warning(f'[爬取任务] 僵尸自愈：同步结束伞进程失败: {pe}')
        if reaped:
            session.commit()
    except Exception as e:
        logger.error(f'[爬取任务] 僵尸自愈执行失败: {e}')
        session.rollback()
    finally:
        if own_session:
            session.close()
    return reaped


def dispatch_scheduled_crawls():
    """
    调度器定时扫描：拾取到期 / 兜底任务并异步执行。

    拾取条件（status=pending 且满足其一）：
    - schedule_type='scheduled' 且 scheduled_at <= now
    - schedule_type='immediate' 且创建已超过 60 秒仍未执行（兜底，防创建线程丢失）

    同时执行「僵尸任务自愈」：清理长时间卡死的 running/pending 任务，
    避免前端横幅永久停留在「任务运行中」。
    """
    from app.core.database import get_db
    from app.model.scheduled_crawl_task import ScheduledCrawlTask

    session = get_db()
    try:
        # 先做僵尸自愈（复用同一 session，超时任务翻 failed）
        reap_stale_crawl_tasks(session)

        now = datetime.now()
        candidates = session.query(ScheduledCrawlTask).filter(
            ScheduledCrawlTask.status == TaskStatus.PENDING
        ).all()

        due = []
        for t in candidates:
            if t.schedule_type == 'scheduled':
                if t.scheduled_at and t.scheduled_at <= now:
                    due.append(t)
            elif t.schedule_type == 'immediate':
                # 兜底：创建超过 60 秒还没被立即线程拉起
                created = t.created_at or now
                if (now - created).total_seconds() > 60:
                    due.append(t)

        for t in due:
            logger.info(f'[爬取任务] 调度器拾取任务 id={t.id} (scope={t.scope}, schedule_type={t.schedule_type})')
            import threading
            thread = threading.Thread(target=_run_scheduled_crawl, args=(t.id,), daemon=True)
            thread.start()
    finally:
        session.close()


# ----------------------------------------------------------------------
# 任务创建 / 校验（被 API 端点调用）
# ----------------------------------------------------------------------
def create_crawl_task(data: dict, created_by: str = 'system') -> dict:
    """
    创建爬取预约任务，返回创建后的任务 to_dict。

    请求体字段：
    - scope: 'semester' | 'all'（必填）
    - semester_id: 指定学期时必填（DB 格式，如 20251）
    - schedule_type: 'immediate' | 'scheduled'（必填）
    - scheduled_at: schedule_type='scheduled' 时必填（ISO 字符串）
    - week: 可选指定周次
    - name: 可选任务名称（不填自动生成）
    """
    from app.core.database import get_db
    from app.model.scheduled_crawl_task import ScheduledCrawlTask

    scope = data.get('scope')
    if scope not in ('semester', 'all'):
        raise ValueError('scope 必须为 "semester" 或 "all"')
    schedule_type = data.get('schedule_type')
    if schedule_type not in ('immediate', 'scheduled'):
        raise ValueError('schedule_type 必须为 "immediate" 或 "scheduled"')

    semester_id = data.get('semester_id')
    eams_id = data.get('eams_id')
    week = data.get('week')

    if scope == 'semester':
        if not semester_id:
            raise ValueError('指定学期爬取时 semester_id 必填')
        semester_id = int(semester_id)
        if not eams_id:
            eams_id = _resolve_eams_id(semester_id)
            if not eams_id:
                raise ValueError(f'无法根据 semester_id={semester_id} 解析教务学期 id')

    # 预约时间校验
    scheduled_at = None
    if schedule_type == 'scheduled':
        sa = data.get('scheduled_at')
        if not sa:
            raise ValueError('预约执行时 scheduled_at 必填')
        if isinstance(sa, str):
            try:
                scheduled_at = datetime.fromisoformat(sa.replace('Z', '+00:00'))
                if scheduled_at.tzinfo:
                    scheduled_at = scheduled_at.replace(tzinfo=None)
            except ValueError:
                raise ValueError('scheduled_at 格式不正确（应为 ISO 时间字符串）')
        elif isinstance(sa, datetime):
            scheduled_at = sa
        if scheduled_at <= datetime.now():
            raise ValueError('预约时间必须晚于当前时间')

    # 自动命名
    if data.get('name'):
        name = data['name']
    elif scope == 'all':
        name = '课表全量爬取（所有学期）'
    else:
        sem_name = _semester_db_id_to_name(semester_id)
        name = f'课表爬取（{sem_name or semester_id}）'

    session = get_db()
    try:
        task = ScheduledCrawlTask(
            name=name,
            scope=scope,
            semester_id=semester_id if scope == 'semester' else None,
            eams_id=eams_id if scope == 'semester' else None,
            schedule_type=schedule_type,
            scheduled_at=scheduled_at,
            week=int(week) if week else None,
            status='pending',
            created_by=created_by,
        )
        session.add(task)
        session.commit()
        session.refresh(task)
        return task.to_dict()
    finally:
        session.close()


def _semester_db_id_to_name(semester_id: int):
    meta = _read_course_meta()
    if not meta:
        return None
    for s in meta.get('semesters', []):
        if _semester_name_to_id(s.get('name', '')) == semester_id:
            return s.get('name')
    return None
