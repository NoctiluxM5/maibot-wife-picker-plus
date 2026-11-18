"""今日老婆 Plus 工具函数与持久化。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger("wife_picker_plus")


async def fetch_avatar_base64(qq: str, size: int = 640, timeout_sec: int = 10) -> Optional[str]:
    """下载指定 QQ 的头像并返回 base64。

    Args:
        qq: 目标 QQ 号。
        size: 头像尺寸（像素）。
        timeout_sec: 单次请求超时秒数。

    Returns:
        Optional[str]: base64 字符串；失败返回 None（调用方只发文字）。
    """

    urls = [
        f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s={size}",
        f"https://q.qlogo.cn/g?b=qq&nk={qq}&s={size}",
    ]
    timeout = aiohttp.ClientTimeout(total=timeout_sec)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in urls:
                try:
                    async with session.get(url) as resp:
                        if resp.status == 200:
                            data = await resp.read()
                            if data:
                                return base64.b64encode(data).decode("utf-8")
                except Exception as exc:  # 单个地址失败继续试下一个
                    logger.debug(f"头像下载失败 {url}: {exc}")
                    continue
    except Exception as exc:
        logger.warning(f"头像下载会话错误: {exc}")
    return None


def today_str(tz_offset_hours: int = 8) -> str:
    """按配置时区返回 YYYY-MM-DD。"""

    offset = max(-12, min(14, int(tz_offset_hours)))
    ts = time.time() + offset * 3600
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


class PersistStore:
    """持久化今日抽取、离婚次数与历史抽中记录。

    兼容上游旧格式：缺少 ``picked_history`` 时按空字典补齐，不丢旧记录。
    """

    def __init__(self, path: str):
        self.path = path
        self.lock = asyncio.Lock()
        self.data: Dict[str, Any] = {
            "daily": {},
            "divorce_usage": {},
            "picked_history": {},
        }
        self._load_sync()

    def _load_sync(self) -> None:
        """从磁盘加载；失败时保持空结构，不影响插件启动。"""

        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.data = {
                    "daily": data.get("daily", {}) or {},
                    "divorce_usage": data.get("divorce_usage", {}) or {},
                    "picked_history": data.get("picked_history", {}) or {},
                }
        except Exception as exc:
            logger.error(f"加载持久化失败: {exc}")
            self.data = {"daily": {}, "divorce_usage": {}, "picked_history": {}}

    async def save(self) -> None:
        """原子写盘：先写临时文件再 rename。"""

        async with self.lock:
            def _write() -> None:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                tmp = f"{self.path}.tmp"
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False)
                os.replace(tmp, self.path)

            try:
                await asyncio.to_thread(_write)
            except Exception as exc:
                logger.error(f"保存持久化失败: {exc}")

    # ---------------- 记录读写 ----------------

    def today_picked_ids(self, group_id: str, today: str) -> List[str]:
        """返回本群今天已经被抽中过的 QQ 列表。"""

        group = (self.data.get("daily") or {}).get(str(group_id), {}) or {}
        return [
            str(rec.get("wife_uid"))
            for rec in group.values()
            if isinstance(rec, dict) and rec.get("date") == today and rec.get("wife_uid")
        ]

    def history(self, group_id: str) -> Dict[str, str]:
        """返回本群「成员 → 最近被抽中日期」。"""

        hist = (self.data.get("picked_history") or {}).get(str(group_id), {}) or {}
        return {str(k): str(v) for k, v in hist.items()}

    def remember_pick(self, group_id: str, uid: str, today: str) -> None:
        """记录某人今天被抽中过。"""

        hist = (self.data.setdefault("picked_history", {}) or {}).setdefault(str(group_id), {})
        hist[str(uid)] = today

    def purge_old(self, today: str, history_days: float = 3.0) -> bool:
        """清理非今日记录与过期历史，返回是否有改动。

        Args:
            today: 今天的日期串。
            history_days: 历史记录保留天数。

        Returns:
            bool: 是否发生了变更（调用方据此决定是否落盘）。
        """

        changed = False
        daily = self.data.setdefault("daily", {})
        divorce = self.data.setdefault("divorce_usage", {})
        history = self.data.setdefault("picked_history", {})

        for gid, members in list(daily.items()):
            for uid in list(members.keys()):
                rec = members.get(uid) or {}
                if rec.get("date") != today:
                    members.pop(uid, None)
                    changed = True
            if not members:
                daily.pop(gid, None)
                changed = True

        for gid, usage in list(divorce.items()):
            for uid in list(usage.keys()):
                if usage.get(uid) != today:
                    usage.pop(uid, None)
                    changed = True
            if not usage:
                divorce.pop(gid, None)
                changed = True

        keep_days = max(1.0, float(history_days or 1.0))
        for gid, picks in list(history.items()):
            for uid, day in list(picks.items()):
                if _days_ago(day, today) > keep_days:
                    picks.pop(uid, None)
                    changed = True
            if not picks:
                history.pop(gid, None)
                changed = True

        return changed


def _days_ago(past: str, today: str) -> float:
    """返回 past 距 today 的天数；解析失败视为很旧（会触发清理）。"""

    try:
        from datetime import date

        y1, m1, d1 = (int(x) for x in str(past).split("-"))
        y2, m2, d2 = (int(x) for x in str(today).split("-"))
        return float((date(y2, m2, d2) - date(y1, m1, d1)).days)
    except (ValueError, AttributeError, TypeError):
        return 9999.0
