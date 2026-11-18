"""补充测试：配置 uniform 必须在任何规模下都不加权。"""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sampling import Member, PickSettings, pick_wife  # noqa: E402

NOW = 1_800_000_000.0
DAY = 86400.0


def m(uid: str, active_days: float = 0.5) -> Member:
    """构造成员。"""

    return Member(
        uid=uid,
        nickname=uid,
        card="",
        last_sent_time=int(NOW - active_days * DAY),
        join_time=int(NOW - 100 * DAY),
    )


class UniformOverrideTests(unittest.TestCase):
    """配置 uniform 时不得加权。"""

    def test_uniform_in_large_group(self) -> None:
        members = [m(f"{i}") for i in range(150)]
        settings = PickSettings(weight_mode="uniform", min_candidates=3)
        outcome = pick_wife(
            members,
            sender="none",
            bot_uid=None,
            settings=settings,
            now=NOW,
            today="2026-11-18",
            rng=random.Random(0),
        )
        self.assertTrue(outcome.ok)
        self.assertIn("uniform", outcome.strategy)
        self.assertEqual(outcome.top3_share, 0.0)

    def test_weighted_when_configured(self) -> None:
        members = [m(f"{i}") for i in range(150)]
        settings = PickSettings(weight_mode="weighted", min_candidates=3)
        outcome = pick_wife(
            members,
            sender="none",
            bot_uid=None,
            settings=settings,
            now=NOW,
            today="2026-11-18",
            rng=random.Random(0),
        )
        self.assertTrue(outcome.ok)
        self.assertIn("weighted", outcome.strategy)

    def test_small_group_forces_uniform_even_if_weighted(self) -> None:
        members = [m(f"{i}") for i in range(10)]
        settings = PickSettings(weight_mode="weighted", min_candidates=3)
        outcome = pick_wife(
            members,
            sender="none",
            bot_uid=None,
            settings=settings,
            now=NOW,
            today="2026-11-18",
            rng=random.Random(0),
        )
        self.assertTrue(outcome.ok)
        self.assertIn("uniform", outcome.strategy)


if __name__ == "__main__":
    unittest.main(verbosity=2)
