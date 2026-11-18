"""抽样核心逻辑（纯函数，不依赖 MaiBot，方便单元测试）。

设计要点：
- 所有策略开关都能退回「旧版行为」：uniform + 不过滤活跃 + 不去重
- 任何一步数据缺失都降级，不抛异常
- 不在消息里暴露概率/权重，只写日志
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------- 数据结构 ----------------


@dataclass(frozen=True)
class Member:
    """群成员的精简视图。

    Attributes:
        uid: QQ 号（字符串）。
        nickname: QQ 昵称。
        card: 群名片，可能为空。
        last_sent_time: 最后发言时间（Unix 秒），0 表示未知。
        join_time: 入群时间（Unix 秒），0 表示未知。
        is_robot: 成员对象是否显式标记为机器人。
    """

    uid: str
    nickname: str = ""
    card: str = ""
    last_sent_time: int = 0
    join_time: int = 0
    is_robot: bool = False

    @property
    def display(self) -> str:
        """展示用名字，优先群名片。"""

        return self.card or self.nickname or "未知昵称"


@dataclass(frozen=True)
class PickSettings:
    """抽样相关配置（从插件配置映射而来）。"""

    exclude_self: bool = True
    exclude_sender: bool = True
    exclude_users: Tuple[str, ...] = ()
    exclude_bots: bool = True
    min_active_days: float = 7.0
    min_join_days: float = 0.0
    weight_mode: str = "uniform"
    alpha: float = 1.0
    max_weight: float = 2.0
    unique_per_day_per_group: bool = True
    recent_penalty_days: float = 3.0
    recent_penalty_factor: float = 0.3
    small_group_size: int = 30
    large_group_size: int = 100
    min_candidates: int = 3


@dataclass(frozen=True)
class Strategy:
    """按群规模决定的抽样策略。"""

    weight_mode: str
    dedupe: bool
    name: str


@dataclass
class PickOutcome:
    """一次抽样的结果与诊断信息。"""

    member: Optional[Member] = None
    reason: str = ""
    strategy: str = ""
    raw_total: int = 0
    after_filter: int = 0
    active_count: int = 0
    top3_share: float = 0.0
    degraded: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """是否抽到了人。"""

        return self.member is not None


# ---------------- 解析 ----------------


def parse_members(raw_members: Sequence[Dict[str, Any]]) -> List[Member]:
    """把适配器返回的成员字典列表转成 :class:`Member`。

    Args:
        raw_members: NapCat ``get_group_member_list`` 的原始返回。

    Returns:
        List[Member]: 解析后的成员，跳过没有 QQ 号的条目。
    """

    result: List[Member] = []
    for raw in raw_members or []:
        if not isinstance(raw, dict):
            continue
        uid = str(raw.get("user_id") or "").strip()
        if not uid:
            continue
        result.append(
            Member(
                uid=uid,
                nickname=str(raw.get("nickname") or ""),
                card=str(raw.get("card") or ""),
                last_sent_time=_as_int(raw.get("last_sent_time")),
                join_time=_as_int(raw.get("join_time")),
                is_robot=bool(raw.get("is_robot", False)),
            )
        )
    return result


def _as_int(value: Any) -> int:
    """尽力把值转成整数，失败返回 0。"""

    try:
        if isinstance(value, bool):
            return 0
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------------- 策略 ----------------


def decide_strategy(total: int, overrides: Optional[Dict[str, Any]] = None) -> Strategy:
    """按群成员总数决定抽样策略。

    Args:
        total: 过滤前的群成员数。
        overrides: 该群的覆盖配置（同名字段优先）。

    Returns:
        Strategy: 权重模式与是否去重。
    """

    overrides = overrides or {}
    # 显式指定去重开关时，任何规模都按它来
    explicit_dedupe = overrides.get("unique_per_day_per_group")
    dedupe_forced = bool(explicit_dedupe) if explicit_dedupe is not None else None

    # 覆盖项里指定了抽样模式，就不再按规模推断
    if overrides.get("weight_mode"):
        mode = str(overrides["weight_mode"]).lower()
        dedupe = dedupe_forced if dedupe_forced is not None else True
        return Strategy(weight_mode=mode, dedupe=dedupe, name=f"override:{mode}")

    size_small = int(overrides.get("small_group_size", 30))
    size_large = int(overrides.get("large_group_size", 100))

    if total < size_small:
        return Strategy(
            weight_mode="uniform",
            dedupe=bool(dedupe_forced) if dedupe_forced is not None else False,
            name="small:uniform",
        )
    if total <= size_large:
        return Strategy(
            weight_mode="weighted",
            dedupe=bool(dedupe_forced) if dedupe_forced is not None else False,
            name="medium:weighted",
        )
    return Strategy(
        weight_mode="weighted",
        dedupe=bool(dedupe_forced) if dedupe_forced is not None else True,
        name="large:weighted+dedupe",
    )


# ---------------- 过滤 ----------------


def filter_members(
    members: Sequence[Member],
    *,
    sender: str,
    bot_uid: Optional[str],
    settings: PickSettings,
    now: float,
    ignore_activity: bool = False,
) -> List[Member]:
    """按配置过滤候选池。

    Args:
        members: 全部成员。
        sender: 指令发起人 QQ。
        bot_uid: 机器人 QQ，None 表示未知。
        settings: 抽样配置。
        now: 当前时间戳（秒）。
        ignore_activity: 为 True 时跳过活跃度/入群时长过滤（用于保底重试）。

    Returns:
        List[Member]: 过滤后的候选。
    """

    blocked = {str(x) for x in settings.exclude_users}
    active_window = settings.min_active_days * 86400.0
    join_window = settings.min_join_days * 86400.0

    pool: List[Member] = []
    for member in members:
        if settings.exclude_sender and member.uid == sender:
            continue
        if bot_uid and settings.exclude_self and member.uid == str(bot_uid):
            continue
        if member.uid in blocked:
            continue
        if settings.exclude_bots and member.is_robot:
            continue
        if not ignore_activity:
            if settings.min_active_days > 0 and member.last_sent_time > 0:
                if now - member.last_sent_time > active_window:
                    continue
            if settings.min_join_days > 0 and member.join_time > 0:
                if now - member.join_time < join_window:
                    continue
        pool.append(member)
    return pool


def count_active(members: Iterable[Member], *, settings: PickSettings, now: float) -> int:
    """统计窗口内有发言的成员数（仅用于日志）。"""

    window = settings.min_active_days * 86400.0
    if window <= 0:
        return sum(1 for _ in members)
    return sum(1 for m in members if m.last_sent_time > 0 and now - m.last_sent_time <= window)


# ---------------- 权重与抽样 ----------------


def member_weight(
    member: Member,
    *,
    settings: PickSettings,
    now: float,
    picked_history: Optional[Dict[str, str]] = None,
    today: str = "",
) -> float:
    """计算单个成员的抽样权重。

    走 ``last_sent_time`` 路径时用「活跃度分档」代替发言条数：
    近 1 天 = 3，近 3 天 = 2，其余 = 1。

    Args:
        member: 成员。
        settings: 配置。
        now: 当前时间戳。
        picked_history: 该群「成员 → 最近一次被抽中日期」。
        today: 今天的日期串，用于判断近期降权。

    Returns:
        float: 权重，最小 1.0。
    """

    weight = 1.0
    if settings.weight_mode == "weighted":
        weight = 1.0 + settings.alpha * math.log1p(_activity_score(member, now))
        weight = max(1.0, min(settings.max_weight, weight))

    if picked_history and today:
        last = picked_history.get(member.uid)
        if last:
            days = _days_between(last, today)
            if days is not None and days < settings.recent_penalty_days:
                weight = max(1.0, weight * settings.recent_penalty_factor)

    return max(1.0, weight)


def _activity_score(member: Member, now: float) -> float:
    """用最后发言时间粗略折算活跃度分档。

    Args:
        member: 成员。
        now: 当前时间戳。

    Returns:
        float: 1 / 2 / 3 三档。
    """

    if member.last_sent_time <= 0:
        return 0.0
    age = now - member.last_sent_time
    if age <= 86400:
        return 3.0
    if age <= 3 * 86400:
        return 2.0
    return 1.0


def _days_between(past: str, today: str) -> Optional[int]:
    """计算两个 YYYY-MM-DD 相差的天数，解析失败返回 None。"""

    try:
        from datetime import date

        y1, m1, d1 = (int(x) for x in past.split("-"))
        y2, m2, d2 = (int(x) for x in today.split("-"))
        return (date(y2, m2, d2) - date(y1, m1, d1)).days
    except (ValueError, AttributeError):
        return None


def weighted_choice(
    members: Sequence[Member],
    weights: Sequence[float],
    rng: Optional[random.Random] = None,
) -> Member:
    """按权重抽一个成员（累积和法，O(n)）。

    Args:
        members: 候选成员。
        weights: 与 members 等长的权重。
        rng: 随机源，默认使用模块级 random。

    Returns:
        Member: 抽中的成员。
    """

    rng = rng or random
    total = sum(max(0.0, w) for w in weights)
    if total <= 0:
        return rng.choice(list(members))
    target = rng.random() * total
    acc = 0.0
    for member, weight in zip(members, weights):
        acc += max(0.0, weight)
        if target <= acc:
            return member
    return members[-1]


def top_share(weights: Sequence[float], top_n: int = 3) -> float:
    """计算权重最高的前 N 名占比（仅用于日志诊断）。"""

    total = sum(max(0.0, w) for w in weights)
    if total <= 0:
        return 0.0
    return sum(sorted((max(0.0, w) for w in weights), reverse=True)[:top_n]) / total


# ---------------- 主入口 ----------------


def pick_wife(
    members: Sequence[Member],
    *,
    sender: str,
    bot_uid: Optional[str],
    settings: PickSettings,
    now: float,
    today: str,
    today_picked: Iterable[str] = (),
    picked_history: Optional[Dict[str, str]] = None,
    overrides: Optional[Dict[str, Any]] = None,
    rng: Optional[random.Random] = None,
) -> PickOutcome:
    """按完整策略抽一位「今日老婆」。

    Args:
        members: 全部成员。
        sender: 发起人 QQ。
        bot_uid: 机器人 QQ。
        settings: 配置。
        now: 当前时间戳。
        today: 今天的日期串。
        today_picked: 本群今天已经被抽中过的 QQ。
        picked_history: 该群的历史抽中记录。
        overrides: 该群的覆盖配置。
        rng: 随机源。

    Returns:
        PickOutcome: 结果与诊断信息。
    """

    outcome = PickOutcome(raw_total=len(members))
    if not members:
        outcome.reason = "empty"
        return outcome

    strategy = decide_strategy(len(members), overrides)
    outcome.strategy = strategy.name
    outcome.active_count = count_active(members, settings=settings, now=now)

    pool = filter_members(
        members, sender=sender, bot_uid=bot_uid, settings=settings, now=now
    )
    if len(pool) < settings.min_candidates:
        relaxed = filter_members(
            members,
            sender=sender,
            bot_uid=bot_uid,
            settings=settings,
            now=now,
            ignore_activity=True,
        )
        if len(relaxed) > len(pool):
            pool = relaxed
            outcome.degraded.append("relaxed_activity")

    if not pool:
        outcome.reason = "no_candidates"
        return outcome

    # 候选太少时放弃加权，退回均匀随机
    weight_mode = strategy.weight_mode
    # 配置显式要求均匀时，任何规模都不加权（小群本来也强制均匀）
    if str(settings.weight_mode).lower() != "weighted":
        weight_mode = "uniform"
    if len(pool) < settings.min_candidates and weight_mode == "weighted":
        weight_mode = "uniform"
        outcome.degraded.append("fallback_uniform")

    outcome.strategy = f"{strategy.name}→{weight_mode}"

    # 同群同日去重
    if strategy.dedupe and settings.unique_per_day_per_group:
        picked = {str(x) for x in today_picked}
        narrowed = [m for m in pool if m.uid not in picked]
        if narrowed:
            pool = narrowed
        else:
            outcome.degraded.append("dedupe_exhausted")

    outcome.after_filter = len(pool)

    if weight_mode != "weighted":
        outcome.member = (rng or random).choice(pool)
        return outcome

    weights = [
        member_weight(
            m,
            settings=settings,
            now=now,
            picked_history=picked_history,
            today=today,
        )
        for m in pool
    ]
    outcome.top3_share = round(top_share(weights), 3)
    outcome.member = weighted_choice(pool, weights, rng)
    return outcome
