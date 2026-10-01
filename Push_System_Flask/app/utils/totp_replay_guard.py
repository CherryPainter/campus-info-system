#!/usr/bin/env python3
"""TOTP 一次性验证码的重放防护（B 级修复项 B9）。

问题（审计事实）：
`TOTP.verify(otp, window=1)` 是**纯函数** —— 只回答「这个码是不是当前窗口（含前后各一个
窗口）的码」，不记录任何「已用过」状态。`UserMFA` 表也没有任何用于记录已用码的字段。
结果是同一个 6 位码在其 **90 秒**（3 个 30 秒窗口）有效期内可被反复提交并且每次都被判为
合法。攻击者只要在该窗口内拿到一次验证码（肩窥、录屏/截图、代理日志、钓鱼页面转发），
就能再完成一次登录 —— 这正是 TOTP 规范要求「一次性」的本意所在。

修复口径：
为每个用户记录「最近一次被成功消费的 TOTP 步号（step = epoch // 30）」，并要求后续
验证所匹配到的步号**严格大于**已记录值。即：一个码只在它所属的那个 30 秒里生效一次。

存储选择：
- 用 Redis（复用项目既有的 Redis 连接工厂，见下方注释），键 `mfa_totp_step:{user_id}`，
  值 = 步号整数，TTL = 窗口跨度 + 余量。过期即自动清理，**不需要新增表、不需要迁移**。
- Redis 不可用时降级为进程内存，并打 WARNING。必须如实承认：多 worker（生产 Gunicorn
  4 workers）下内存降级只能挡住「重放请求恰好落到同一 worker」的情况，是降级不是等价；
  但至少比完全不设防好，且与限流/登录爆破的既有降级口径一致。

已知的行为代价（有意接受）：
同一个 30 秒窗口内不能连续完成两次需要验证码的操作（例如刚在个人中心用码启用 MFA，
紧接着又用同一个码登录），需要等下一个窗口（最多 30 秒）。这是「一次性」的固有语义，
不是缺陷；错误提示仍是「验证码错误」，用户重试下一个码即可。
"""

import hashlib
import threading
import time

from app.core.logger import get_logger

logger = get_logger(__name__)

STEP_INTERVAL = 30  # TOTP 时间步长（秒），与 TOTP 默认 interval 保持一致
DEFAULT_WINDOW = 1  # 容错窗口：当前步前后各 1 个

# 键 TTL：覆盖 window=1 的全部可能步号（3 个步），再留一段余量，
# 保证「过期」只发生在该码绝不可能再被接受之后，不会把有效记录提前清掉。
_STEP_TTL = (2 * DEFAULT_WINDOW + 1) * STEP_INTERVAL + 60

_LOCK = threading.Lock()
# 内存降级表：key -> (step, 过期时间戳)。仅在 Redis 不可用时使用。
_MEMORY: dict[str, tuple[int, float]] = {}


def _redis():
    """取 Redis 客户端；不可用返回 None（走内存降级）。

    这里刻意复用 `ip_blacklist_service._get_redis_client`：它是本项目唯一的 Redis 连接
    工厂，自带「失败进入冷却期、冷却过后自动重连」的降级策略。另建一个工厂等于把连接
    参数与降级策略抄成第二份，Redis 配置一改就会出现两套行为不一致。
    （命名上它挂在 IP 黑名单模块下确实不够贴切，属已知的命名债，见审计报告 §7。）
    """
    from app.services import ip_blacklist_service

    return ip_blacklist_service._get_redis_client()


def _key(user_id) -> str:
    return f"mfa_totp_step:{user_id}"


def _is_new_step(current, step: int) -> bool:
    """步号规则（唯一一处定义）：没有记录、或记录严格小于本次步号 → 允许。

    内存降级路径直接调用本函数；Redis 路径由下方 Lua 脚本**同义转写**（无法在无 Redis
    环境执行 Lua，故用测试锁定两者表达式一致，避免改了一边忘了另一边）。
    """
    return current is None or int(current) < int(step)


def _claim_memory(key: str, step: int, ttl: int) -> bool:
    now = time.time()
    with _LOCK:
        # 顺手清理过期项，避免无 Redis 的长期进程里表越积越大
        for k in [k for k, (_, exp) in _MEMORY.items() if exp <= now]:
            _MEMORY.pop(k, None)
        record = _MEMORY.get(key)
        if not _is_new_step(record[0] if record else None, step):
            return False
        _MEMORY[key] = (step, now + ttl)
        return True


_CLAIM_LUA = """
local cur = redis.call('GET', KEYS[1])
if cur and tonumber(cur) >= tonumber(ARGV[1]) then
    return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
return 1
"""
# 与 _is_new_step 同义：cur 存在且 cur >= step → 拒绝（返回 0），否则写入并放行。
# 用 Lua 在 Redis 侧一次完成「比较 + 写入」，避免「读-改-写」竞态下并发请求都通过。


def is_replay(user_id, step: int) -> bool:
    """判断 `step` 是否为已被消费过的步号；否则占用它并返回 False。

    语义为「原子地比较并占用」：只有严格大于已记录步号时才写入并放行。用 Lua 脚本在
    Redis 侧完成比较+写入，避免「读-改-写」竞态下发两个并发请求都通过。

    Redis 不可用时退化为进程内存实现（见模块 docstring 的降级说明）。
    """
    key = _key(user_id)
    rc = _redis()
    if rc is not None:
        try:
            accepted = rc.eval(_CLAIM_LUA, 1, key, int(step), _STEP_TTL)
            return not int(accepted)
        except Exception as exc:  # 运行期 Redis 抖动：降级内存，不阻断登录
            logger.warning(f"[MFA重放防护] Redis 写入失败（{exc}），本次降级为进程内存")
    else:
        logger.warning(
            "[MFA重放防护] Redis 不可用，降级为进程内存 —— "
            "多 worker 部署下只能挡住落到同一 worker 的重放请求"
        )
    return not _claim_memory(key, int(step), _STEP_TTL)


def reset(user_id) -> None:
    """清除某用户的已用步号记录（重置 MFA / 测试用）。"""
    key = _key(user_id)
    rc = _redis()
    if rc is not None:
        try:
            rc.delete(key)
        except Exception as exc:
            logger.warning(f"[MFA重放防护] Redis 清除失败（{exc}），继续清理内存副本")
    with _LOCK:
        _MEMORY.pop(key, None)


def key_fingerprint(user_id) -> str:
    """键的短指纹，仅用于日志/测试断言，避免把用户标识原样写进日志。"""
    return hashlib.sha256(str(user_id).encode()).hexdigest()[:12]
