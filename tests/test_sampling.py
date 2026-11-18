"""抽样逻辑的单元测试（不依赖 MaiBot，可直接 python -m unittest 运行）。"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

# 允许直接运行本文件
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sampling import (  # noqa: E402
    Member,
    PickSettings,
    count_active,
    decide_strategy,
    filter_members,
    member_weight,
    parse_members,
    pick_wife,
    top_share,
    weighted_choice,
)

NOW = 1_800_000_000.0
DAY = 86400.0


def member(uid: str, *, active_days: float = 0.5, join_days: float = 100, robot: bool = False) -> Member:
    """构造一个成员，active_days 表示「多少天前发过言」。"""

    return Member(
        uid=uid,
        nickname=f"nick{uid}",
        card=f"card{uid}",
        last_sent_time=int(NOW - active_days * DAY) if active_days < 999 else 0,
        join_time=int(NOW - join_days * DAY),
        is_robot=robot,
    )


class ParseTests(unittest.TestCase):
    """成员解析。"""

    def test_parse_skips_empty_uid(self) -> None:
        raw = [
            {"user_id": 123, "nickname": "a", "card": "A"},
            {"user_id": "", "nickname": "b"},
            {"nickname": "no id"},
        ]
        members = parse_members(raw)
        self.assertEqual(len(members), 1)
        self.assertEqual(members[0].uid, "123")
        self.assertEqual(members[0].display, "A")

    def test_parse_handles_missing_optional_fields(self) -> None:
        members = parse_members([{"user_id": "42"}])
        self.assertEqual(members[0].last_sent_time, 0)
        self.assertEqual(members[0].join_time, 0)
        self.assertFalse(members[0].is_robot)


class FilterTests(unittest.TestCase):
    """候选池过滤。"""

    def setUp(self) -> None:
        self.settings = PickSettings(min_active_days=7.0, exclude_users=("999",))

    def test_excludes_sender_self_and_blacklist(self) -> None:
        members = [
            member("1"),  # sender
            member("2"),  # bot
            member("999"),  # 黑名单
            member("3"),
        ]
        pool = filter_members(
            members, sender="1", bot_uid="2", settings=self.settings, now=NOW
        )
        self.assertEqual([m.uid for m in pool], ["3"])

    def test_excludes_inactive_members(self) -> None:
        members = [member("1", active_days=0.1), member("2", active_days=30)]
        pool = filter_members(
            members, sender="x", bot_uid=None, settings=self.settings, now=NOW
        )
        self.assertEqual([m.uid for m in pool], ["1"])

    def test_unknown_last_sent_time_is_kept(self) -> None:
        members = [member("1", active_days=999)]  # 0 表示未知
        pool = filter_members(
            members, sender="x", bot_uid=None, settings=self.settings, now=NOW
        )
        self.assertEqual([m.uid for m in pool], ["1"])

    def test_robot_member_excluded(self) -> None:
        members = [member("1", robot=True), member("2")]
        pool = filter_members(
            members, sender="x", bot_uid=None, settings=self.settings, now=NOW
        )
        self.assertEqual([m.uid for m in pool], ["2"])

    def test_ignore_activity_keeps_everyone(self) -> None:
        members = [member("1", active_days=30), member("2", active_days=60)]
        pool = filter_members(
            members,
            sender="x",
            bot_uid=None,
            settings=self.settings,
            now=NOW,
            ignore_activity=True,
        )
        self.assertEqual(len(pool), 2)


class StrategyTests(unittest.TestCase):
    """群规模策略。"""

    def test_small_group_is_uniform_without_dedupe(self) -> None:
        strategy = decide_strategy(10, {})
        self.assertEqual(strategy.weight_mode, "uniform")
        self.assertFalse(strategy.dedupe)

    def test_medium_group_is_weighted(self) -> None:
        strategy = decide_strategy(60, {})
        self.assertEqual(strategy.weight_mode, "weighted")
        self.assertFalse(strategy.dedupe)

    def test_large_group_is_weighted_with_dedupe(self) -> None:
        strategy = decide_strategy(200, {})
        self.assertEqual(strategy.weight_mode, "weighted")
        self.assertTrue(strategy.dedupe)

    def test_override_wins(self) -> None:
        strategy = decide_strategy(200, {"weight_mode": "uniform"})
        self.assertEqual(strategy.weight_mode, "uniform")


class WeightTests(unittest.TestCase):
    """权重计算。"""

    def test_inactive_member_has_min_weight(self) -> None:
        settings = PickSettings(weight_mode="weighted", alpha=1.0, max_weight=2.0)
        m = member("1", active_days=30)
        self.assertGreaterEqual(member_weight(m, settings=settings, now=NOW), 1.0)

    def test_active_member_weight_is_capped(self) -> None:
        settings = PickSettings(weight_mode="weighted", alpha=1.0, max_weight=2.0)
        m = member("1", active_days=0.1)
        self.assertLessEqual(member_weight(m, settings=settings, now=NOW), 2.0)

    def test_recent_penalty_lowers_weight(self) -> None:
        settings = PickSettings(weight_mode="weighted", alpha=1.0, max_weight=3.0)
        m = member("1", active_days=0.1)
        normal = member_weight(m, settings=settings, now=NOW)
        penalized = member_weight(
            m, settings=settings, now=NOW, picked_history={"1": "2026-11-17"}, today="2026-11-18"
        )
        self.assertLess(penalized, normal)
        self.assertGreaterEqual(penalized, 1.0)

    def test_uniform_mode_ignores_activity(self) -> None:
        settings = PickSettings(weight_mode="uniform")
        active = member_weight(member("1", active_days=0.1), settings=settings, now=NOW)
        idle = member_weight(member("2", active_days=30), settings=settings, now=NOW)
        self.assertEqual(active, idle)


class SamplingTests(unittest.TestCase):
    """加权抽样与主流程。"""

    def test_weighted_choice_respects_weights(self) -> None:
        members = [member("a"), member("b")]
        rng = random.Random(0)
        picks = {"a": 0, "b": 0}
        for _ in range(2000):
            picks[weighted_choice(members, [9.0, 1.0], rng).uid] += 1
        self.assertGreater(picks["a"], picks["b"] * 3)

    def test_top_share(self) -> None:
        self.assertAlmostEqual(top_share([1, 1, 1, 1], top_n=2), 0.5, places=3)

    def test_pick_avoids_today_picked_member(self) -> None:
        members = [member("1"), member("2"), member("3")]
        settings = PickSettings(unique_per_day_per_group=True)
        outcome = pick_wife(
            members,
            sender="9",
            bot_uid=None,
            settings=settings,
            now=NOW,
            today="2026-11-18",
            today_picked=["1", "2"],
            overrides={"unique_per_day_per_group": True},
            rng=random.Random(1),
        )
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.member.uid, "3")

    def test_dedupe_exhausted_falls_back(self) -> None:
        members = [member("1"), member("2"), member("3")]
        settings = PickSettings(unique_per_day_per_group=True)
        outcome = pick_wife(
            members,
            sender="9",
            bot_uid=None,
            settings=settings,
            now=NOW,
            today="2026-11-18",
            today_picked=["1", "2", "3"],
            overrides={"unique_per_day_per_group": True},
            rng=random.Random(2),
        )
        self.assertTrue(outcome.ok)
        self.assertIn("dedupe_exhausted", outcome.degraded)

    def test_small_pool_relaxes_activity(self) -> None:
        members = [member("1", active_days=30), member("2", active_days=40)]
        settings = PickSettings(min_active_days=7.0, min_candidates=3)
        outcome = pick_wife(
            members,
            sender="9",
            bot_uid=None,
            settings=settings,
            now=NOW,
            today="2026-11-18",
            rng=random.Random(3),
        )
        self.assertTrue(outcome.ok)
        self.assertIn("relaxed_activity", outcome.degraded)

    def test_empty_pool_reports_reason(self) -> None:
        members = [member("1")]
        settings = PickSettings(min_candidates=3)
        outcome = pick_wife(
            members,
            sender="1",
            bot_uid="1",
            settings=settings,
            now=NOW,
            today="2026-11-18",
        )
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "no_candidates")

    def test_count_active(self) -> None:
        members = [member("1", active_days=1), member("2", active_days=30), member("3", active_days=999)]
        settings = PickSettings(min_active_days=7.0)
        self.assertEqual(count_active(members, settings=settings, now=NOW), 1)

    def test_weighted_mode_still_works_end_to_end(self) -> None:
        members = [member(f"{i}", active_days=0.5) for i in range(120)]
        members.append(member("idle", active_days=30))
        settings = PickSettings(weight_mode="weighted", min_active_days=0.0)
        rng = random.Random(7)
        picks = 0
        for _ in range(300):
            outcome = pick_wife(
                members,
                sender="999",
                bot_uid=None,
                settings=settings,
                now=NOW,
                today="2026-11-18",
                overrides={"weight_mode": "weighted"},
                rng=rng,
            )
            self.assertTrue(outcome.ok)
            picks += 1
        self.assertEqual(picks, 300)


if __name__ == "__main__":
    unittest.main(verbosity=2)
