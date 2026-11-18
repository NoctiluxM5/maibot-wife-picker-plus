"""今日老婆 Plus —— 活跃度感知 + 去重 + 群规模自适应的抽样版「今日老婆」。"""

from __future__ import annotations

import asyncio
import os
import random
import time
from typing import Any, Dict, List, Optional, Tuple

from maibot_sdk import CONFIG_RELOAD_SCOPE_SELF, Command, MaiBotPlugin

from .config import WifePickerConfig
from .sampling import Member, PickOutcome, PickSettings, parse_members, pick_wife
from .utils import PersistStore, fetch_avatar_base64, today_str

# 数据文件名与上游不同，两个插件可以同时安装、互不干扰
_DATA_FILE = "wife_picker_plus_seen.json"


class WifePickerPlusPlugin(MaiBotPlugin):
    """抽取今日老婆：过滤死号、当日去重、按群规模选策略。"""

    config_model = WifePickerConfig

    # ---------------- 生命周期 ----------------

    async def on_load(self) -> None:
        data_dir = os.path.join(os.path.dirname(__file__), "data")
        os.makedirs(data_dir, exist_ok=True)
        self._store = PersistStore(os.path.join(data_dir, _DATA_FILE))
        self._last_action: Dict[str, Dict[str, Any]] = {}
        self._bot_qq_cache: Optional[str] = None
        self._locks: Dict[str, asyncio.Lock] = {}
        self._member_cache: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
        self._activity_warned = False
        self.ctx.logger.info("✅ wife_picker_plus 已加载（活跃度感知抽样）")

    async def on_unload(self) -> None:
        store = getattr(self, "_store", None)
        if store is not None:
            await store.save()

    async def on_config_update(self, scope: str, config_data: dict, version: str) -> None:
        if scope == CONFIG_RELOAD_SCOPE_SELF:
            self.ctx.logger.info(f"wife_picker_plus 配置已更新: {version}")
            self._bot_qq_cache = None
            self._member_cache.clear()

    # ---------------- 上下文解析 ----------------

    def _extract_ctx(self, kwargs: dict) -> Tuple[Optional[str], Optional[str], str]:
        """从命令回调里取群号、发起人 QQ 与显示名。"""

        base_info = kwargs.get("message_base_info", {}) or {}
        user_info = base_info.get("user_info", {}) or {}
        group_info = base_info.get("group_info", {}) or {}

        group_id = kwargs.get("group_id") or group_info.get("group_id")
        sender_qq = kwargs.get("user_id") or user_info.get("user_id")

        raw_event = kwargs.get("raw_event")
        if not group_id and raw_event is not None:
            group_id = (
                raw_event.get("group_id")
                if isinstance(raw_event, dict)
                else getattr(raw_event, "group_id", None)
            )
        if not sender_qq and raw_event is not None:
            sender_qq = (
                raw_event.get("user_id")
                if isinstance(raw_event, dict)
                else getattr(raw_event, "user_id", None)
            )

        sender_name = user_info.get("user_cardname") or user_info.get("user_nickname") or ""
        return (
            str(group_id) if group_id else None,
            str(sender_qq) if sender_qq else None,
            sender_name,
        )

    async def _resolve_bot_qq(self) -> Optional[str]:
        """解析机器人自身 QQ，优先配置、其次适配器。"""

        if self._bot_qq_cache:
            return self._bot_qq_cache
        cfg_qq = (self.config.wife_picker.bot_qq or "").strip()
        if cfg_qq:
            self._bot_qq_cache = cfg_qq
            return cfg_qq
        try:
            info = await self.ctx.api.call("adapter.napcat.system.get_login_info")
            if isinstance(info, dict):
                uid = info.get("user_id") or (info.get("data") or {}).get("user_id")
                if uid:
                    self._bot_qq_cache = str(uid)
                    return self._bot_qq_cache
        except Exception as exc:
            self.ctx.logger.warning(f"无法自动获取机器人 QQ: {exc}")
        return None

    # ---------------- 成员列表（带缓存） ----------------

    async def _get_members(self, group_id: str) -> List[Dict[str, Any]]:
        """拉取群成员列表，按配置做短缓存。

        Args:
            group_id: 群号。

        Returns:
            List[Dict[str, Any]]: 原始成员列表。

        Raises:
            RuntimeError: 适配器调用失败时抛出，由调用方转成用户提示。
        """

        ttl = max(0, int(self.config.wife_picker.member_cache_seconds or 0))
        now = time.time()
        cached = self._member_cache.get(group_id)
        if ttl > 0 and cached and now - cached[0] < ttl:
            return cached[1]

        members = await self.ctx.api.call(
            "adapter.napcat.group.get_group_member_list",
            group_id=int(group_id),
            no_cache=True,
        )
        if not isinstance(members, list):
            raise RuntimeError("成员列表格式异常")
        if ttl > 0:
            self._member_cache[group_id] = (now, members)
        return members

    # ---------------- 发送 ----------------

    async def _send_napcat(self, group_id: int, message_chain: list) -> None:
        """通过适配器发送群消息。"""

        try:
            await self.ctx.api.call(
                "adapter.napcat.message.send_msg",
                params={
                    "message_type": "group",
                    "group_id": int(group_id),
                    "message": message_chain,
                },
            )
        except Exception as exc:
            self.ctx.logger.error(f"napcat 发送失败: {exc}")

    async def _send_text_at(self, group_id: str, sender_qq: str, text: str) -> None:
        """发送「@某人 + 文本」。"""

        chain: list = []
        if sender_qq and sender_qq.isdigit():
            chain.append({"type": "at", "data": {"qq": str(sender_qq)}})
            chain.append({"type": "text", "data": {"text": " "}})
        chain.append({"type": "text", "data": {"text": text}})
        await self._send_napcat(int(group_id), chain)

    async def _send_wife_message(
        self,
        group_id: str,
        sender_qq: str,
        wife_uid: str,
        wife_nick: str,
        wife_card: str,
        prefix: str,
    ) -> None:
        """发送抽取结果（@发起人 + 文本 + 可选头像）。"""

        nick = wife_nick or "未知昵称"
        lines = [f"\n💕 {prefix}：", f"🌸 QQ名：{nick}"]
        if wife_card and wife_card != wife_nick:
            lines.append(f"🏷️ 群昵称：{wife_card}")
        lines.append(f"🆔 QQ号：{wife_uid}")
        text = "\n".join(lines)

        chain: list = []
        if sender_qq and sender_qq.isdigit():
            chain.append({"type": "at", "data": {"qq": str(sender_qq)}})
        chain.append({"type": "text", "data": {"text": text}})

        if self.config.wife_picker.send_avatar:
            size = int(self.config.wife_picker.avatar_size or 640)
            b64 = await fetch_avatar_base64(wife_uid, size=size)
            if b64:
                chain.append({"type": "text", "data": {"text": "\n"}})
                chain.append({"type": "image", "data": {"file": f"base64://{b64}"}})

        await self._send_napcat(int(group_id), chain)

    # ---------------- 冷却 ----------------

    def _check_cooldown(self, group_id: str, sender_qq: str, command: str) -> bool:
        """True 表示命中冷却，应当静默拦截。"""

        key = f"{group_id}_{sender_qq}"
        now = time.time()
        last = self._last_action.get(key, {})
        cooldown = max(0, int(self.config.wife_picker.cooldown_seconds or 60))
        if last.get("command") == command and now - last.get("time", 0.0) < cooldown:
            return True
        self._last_action[key] = {"command": command, "time": now}
        return False

    # ---------------- 配置映射 ----------------

    def _settings_for(self, group_id: str) -> PickSettings:
        """把插件配置（含分群覆盖）映射成抽样配置。"""

        cfg = self.config.wife_picker
        override = (cfg.group_overrides or {}).get(str(group_id), {}) or {}

        base: Dict[str, Any] = {
            "exclude_self": bool(cfg.exclude_self),
            "exclude_sender": bool(cfg.exclude_sender),
            "exclude_users": tuple(str(x) for x in (cfg.exclude_users or [])),
            "exclude_bots": bool(cfg.exclude_bots),
            "min_active_days": float(cfg.min_active_days),
            "min_join_days": float(cfg.min_join_days),
            "weight_mode": str(cfg.weight_mode or "uniform").lower(),
            "alpha": float(cfg.alpha),
            "max_weight": float(cfg.max_weight),
            "unique_per_day_per_group": bool(cfg.unique_per_day_per_group),
            "recent_penalty_days": float(cfg.recent_penalty_days),
            "recent_penalty_factor": float(cfg.recent_penalty_factor),
            "small_group_size": int(cfg.small_group_size),
            "large_group_size": int(cfg.large_group_size),
            "min_candidates": int(cfg.min_candidates),
        }
        for key, value in override.items():
            if key in base:
                base[key] = value
        return PickSettings(**base)

    # ---------------- /今日老婆 ----------------

    @Command("wife_picker_plus", description="随机抽取今日老婆（活跃度感知）", pattern=r"^/今日老婆$")
    async def handle_wife_picker(self, stream_id: str = "", **kwargs):
        """处理 /今日老婆。"""

        if not self.config.plugin.enabled:
            return False, None, False

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "好像是私聊呢，去群聊里找你的老婆吧。", True

        if self._check_cooldown(group_id, sender_qq, "wife_picker"):
            self.ctx.logger.info(f"用户 {sender_qq} 在群 {group_id} 触发冷却，静默忽略。")
            return True, "cooldown", True

        cfg = self.config.wife_picker
        today = today_str(cfg.tz_offset_hours)

        if self._store.purge_old(today, history_days=cfg.recent_penalty_days) and cfg.persist_enabled:
            await self._store.save()

        no_limit = {str(x) for x in (cfg.no_limit_users or [])}
        daily = self._store.data.setdefault("daily", {})

        # 今日已抽：复读记录
        if sender_qq not in no_limit:
            rec = daily.get(group_id, {}).get(sender_qq)
            if isinstance(rec, dict) and rec.get("date") == today:
                await self._send_wife_message(
                    group_id,
                    sender_qq,
                    str(rec.get("wife_uid", "未知")),
                    str(rec.get("wife_nick", "")),
                    str(rec.get("wife_card", "")),
                    prefix="你今天已经有老婆了哦，她是",
                )
                return True, "already_picked", True

        # 拉成员
        try:
            raw_members = await self._get_members(group_id)
        except Exception as exc:
            self.ctx.logger.error(f"获取群成员失败: {exc}")
            await self._send_text_at(group_id, sender_qq, f"无法获取群成员列表：{exc}")
            return False, "api_error", True

        members = parse_members(raw_members)
        if not members:
            await self._send_text_at(group_id, sender_qq, "群成员列表数据异常。")
            return False, "api_error", True

        bot_qq = await self._resolve_bot_qq() if cfg.exclude_self else None
        settings = self._settings_for(group_id)
        overrides = (cfg.group_overrides or {}).get(str(group_id), {}) or {}
        start = time.perf_counter()

        # 同群串行，避免并发抽到同一个人
        lock = self._locks.setdefault(group_id, asyncio.Lock())
        async with lock:
            today_ids = self._store.today_picked_ids(group_id, today)
            history = self._store.history(group_id)

            outcome = pick_wife(
                members,
                sender=sender_qq,
                bot_uid=bot_qq,
                settings=settings,
                now=time.time(),
                today=today,
                today_picked=today_ids,
                picked_history=history,
                overrides=overrides,
            )

            if cfg.shadow_mode:
                # 影子模式：结果仍走旧逻辑，仅记录新策略会抽到谁
                legacy_pool = [
                    m
                    for m in members
                    if not (settings.exclude_sender and m.uid == sender_qq)
                    and not (bot_qq and settings.exclude_self and m.uid == str(bot_qq))
                ]
                if not legacy_pool:
                    await self._send_text_at(
                        group_id, sender_qq, "群里好像没人了（或者只有你和机器人）..."
                    )
                    return True, "no_candidates", True
                chosen = random.choice(legacy_pool)
                self._log_pick(group_id, outcome, chosen, start, shadow=True)
            else:
                chosen = outcome.member

            if chosen is None:
                reason = outcome.reason or "no_candidates"
                if reason == "empty":
                    await self._send_text_at(group_id, sender_qq, "群成员列表数据异常。")
                else:
                    await self._send_text_at(
                        group_id, sender_qq, "群里好像没人了（或者只有你和机器人）..."
                    )
                return True, reason, True

            # 先发消息，再落盘；落盘失败也不影响用户看到结果
            await self._send_wife_message(
                group_id,
                sender_qq,
                chosen.uid,
                chosen.nickname,
                chosen.card,
                prefix="今天你的老婆是",
            )

            daily.setdefault(group_id, {})[sender_qq] = {
                "date": today,
                "wife_uid": chosen.uid,
                "wife_nick": chosen.nickname,
                "wife_card": chosen.card,
            }
            self._store.remember_pick(group_id, chosen.uid, today)
            if cfg.persist_enabled:
                await self._store.save()

            if not cfg.shadow_mode:
                self._log_pick(group_id, outcome, chosen, start, shadow=False)

        return True, f"wife picked: {chosen.display}", True

    def _log_pick(
        self,
        group_id: str,
        outcome: PickOutcome,
        chosen: Member,
        start: float,
        *,
        shadow: bool,
    ) -> None:
        """输出一行结构化抽取日志。"""

        if not self.config.wife_picker.verbose_log:
            return
        cost_ms = (time.perf_counter() - start) * 1000
        tag = "shadow" if shadow else "pick"
        # 抽中者有多久没说话，方便核对过滤是否生效
        if chosen.last_sent_time > 0:
            idle_txt = f"{(time.time() - chosen.last_sent_time) / 86400:.1f}天"
        else:
            idle_txt = "未知"
        self.ctx.logger.info(
            f"[{tag}] 群={group_id} 总成员={outcome.raw_total} 活跃={outcome.active_count} "
            f"过滤后={outcome.after_filter} 策略={outcome.strategy} "
            f"抽中={chosen.display}({chosen.uid}) 闲置={idle_txt} 用时={cost_ms:.1f}ms "
            f"降级={','.join(outcome.degraded) or '无'} 前三占比={outcome.top3_share}"
        )
        if outcome.degraded:
            self.ctx.logger.warning(
                f"群={group_id} 抽取发生降级: {','.join(outcome.degraded)}"
            )

    # ---------------- /离婚 ----------------

    @Command(
        "wife_picker_plus_divorce",
        description="清空今日老婆记录，可重新抽取（每日限一次）",
        pattern=r"^/离婚$",
    )
    async def handle_divorce(self, stream_id: str = "", **kwargs):
        """处理 /离婚（行为与上游一致）。"""

        if not self.config.plugin.enabled:
            return False, None, False

        group_id, sender_qq, _ = self._extract_ctx(kwargs)
        if not group_id or not sender_qq:
            return True, "只能在群里离婚喔～", True

        if self._check_cooldown(group_id, sender_qq, "divorce"):
            self.ctx.logger.info(f"用户 {sender_qq} 在群 {group_id} 触发离婚冷却，静默忽略。")
            return True, "cooldown", True

        cfg = self.config.wife_picker
        today = today_str(cfg.tz_offset_hours)

        if self._store.purge_old(today, history_days=cfg.recent_penalty_days) and cfg.persist_enabled:
            await self._store.save()

        # 离婚白名单 = 无限抽取名单 ∪ 无限离婚名单
        no_limit_divorce = {str(x) for x in (cfg.no_limit_users or [])} | {
            str(x) for x in (cfg.unlimited_divorce_users or [])
        }
        daily = self._store.data.setdefault("daily", {})
        divorce_usage = self._store.data.setdefault("divorce_usage", {})

        if sender_qq not in no_limit_divorce:
            if divorce_usage.get(group_id, {}).get(sender_qq) == today:
                await self._send_text_at(
                    group_id, sender_qq, "感情不是儿戏，明天再来吧。（每日仅限一次离婚）"
                )
                return True, "limit_reached", True

        group_daily = daily.get(group_id, {})
        if sender_qq in group_daily:
            group_daily.pop(sender_qq, None)
            divorce_usage.setdefault(group_id, {})[sender_qq] = today
            if cfg.persist_enabled:
                await self._store.save()
            await self._send_text_at(group_id, sender_qq, "已经离婚成功，现在可以重新抽你的新老婆啦～")
            return True, "divorced", True

        await self._send_text_at(group_id, sender_qq, "你今天还没有老婆呢，不需要离婚～")
        return True, "no_record", True


def create_plugin():
    """插件工厂。"""

    return WifePickerPlusPlugin()
