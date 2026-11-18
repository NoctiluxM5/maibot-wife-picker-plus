"""今日老婆 Plus 配置模型。"""

from __future__ import annotations

from typing import ClassVar, Dict, List

from maibot_sdk import Field, PluginConfigBase


class PluginSection(PluginConfigBase):
    """插件总开关。"""

    __ui_label__: ClassVar[str] = "插件开关"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=True,
        description="是否启用本插件。",
        json_schema_extra={"label": "启用插件", "order": 0},
    )
    config_version: str = Field(
        default="1.0.0",
        json_schema_extra={"disabled": True, "hidden": True, "label": "配置版本", "order": 99},
    )


class WifePickerSection(PluginConfigBase):
    """抽取规则（沿用上游命名，避免老配置失效）。"""

    __ui_label__: ClassVar[str] = "今日老婆设置"
    __ui_order__: ClassVar[int] = 1

    # —— 原有配置（保持不变） ——
    exclude_self: bool = Field(
        default=True,
        description="是否将机器人自身排除出候选池。",
        json_schema_extra={"label": "排除机器人自身", "order": 0},
    )
    exclude_sender: bool = Field(
        default=True,
        description="是否将指令发起者排除出候选池。",
        json_schema_extra={"label": "排除指令发起者", "order": 1},
    )
    bot_qq: str = Field(
        default="",
        description="（可选）机器人 QQ。留空时自动通过适配器获取。",
        json_schema_extra={"label": "机器人 QQ（可选）", "placeholder": "留空自动获取", "order": 2},
    )
    no_limit_users: List[str] = Field(
        default_factory=list,
        description="不受「每天只能抽一次」限制的 QQ（每次触发都重新抽）。一般留空即可。",
        json_schema_extra={"label": "无限抽取 QQ", "order": 3},
    )
    unlimited_divorce_users: List[str] = Field(
        default_factory=list,
        description="不受「每天只能离婚一次」限制的 QQ（可以反复离婚重抽，抽取本身仍按每日一次复读）。",
        json_schema_extra={"label": "无限离婚 QQ", "order": 4},
    )
    tz_offset_hours: int = Field(
        default=8,
        description="时区偏移（小时），用于确定「今日」的边界。",
        json_schema_extra={"label": "时区偏移", "order": 4, "step": 1},
    )
    send_avatar: bool = Field(
        default=True,
        description="是否额外发送对方的 QQ 头像。",
        json_schema_extra={"label": "发送头像", "order": 5},
    )
    avatar_size: int = Field(
        default=640,
        description="头像尺寸（像素）。",
        json_schema_extra={"label": "头像尺寸", "order": 6, "step": 1},
    )
    cooldown_seconds: int = Field(
        default=60,
        description="同一指令连续触发的冷却秒数。",
        json_schema_extra={"label": "冷却秒数", "order": 7, "step": 1},
    )
    persist_enabled: bool = Field(
        default=True,
        description="是否启用本地持久化（保存今日抽取与离婚记录）。",
        json_schema_extra={"label": "启用持久化", "order": 8},
    )

    # —— 新增：过滤 ——
    exclude_users: List[str] = Field(
        default_factory=list,
        description="手工黑名单 QQ：永远不参与抽取（老板号、测试号等）。",
        json_schema_extra={"label": "黑名单 QQ", "order": 10},
    )
    exclude_bots: bool = Field(
        default=True,
        description="成员对象显式标记为机器人时排除。",
        json_schema_extra={"label": "排除机器人账号", "order": 11},
    )
    min_active_days: float = Field(
        default=7.0,
        description="超过这么多天没发言的成员不参与抽取；0 表示不按活跃度过滤。",
        json_schema_extra={"label": "活跃度门槛（天）", "order": 12, "step": 0.5},
    )
    min_join_days: float = Field(
        default=0.0,
        description="入群不足这么多天的新人不参与抽取；0 表示不限制。",
        json_schema_extra={"label": "入群时长门槛（天）", "order": 13, "step": 0.5},
    )

    # —— 新增：抽样 ——
    weight_mode: str = Field(
        default="uniform",
        description="uniform = 每人等概率；weighted = 越活跃权重越高（上限 max_weight）。",
        json_schema_extra={
            "label": "抽样模式",
            "order": 14,
            "options": ["uniform", "weighted"],
        },
    )
    alpha: float = Field(
        default=1.0,
        description="加权模式的强度系数，仅在 weight_mode=weighted 时生效。",
        json_schema_extra={"label": "加权系数 alpha", "order": 15, "step": 0.1},
    )
    max_weight: float = Field(
        default=2.0,
        description="单个成员的最大权重，防止话痨垄断。",
        json_schema_extra={"label": "最大权重", "order": 16, "step": 0.5},
    )

    # —— 新增：去重 ——
    unique_per_day_per_group: bool = Field(
        default=True,
        description="同一天同一群里不重复抽到同一个人（候选不够时自动放开）。",
        json_schema_extra={"label": "当日同群去重", "order": 17},
    )
    recent_penalty_days: float = Field(
        default=3.0,
        description="最近这些天被抽中过的人会降权。",
        json_schema_extra={"label": "近期降权天数", "order": 18, "step": 0.5},
    )
    recent_penalty_factor: float = Field(
        default=0.3,
        description="近期被抽中者的权重倍数（最低仍按 1.0 计算）。",
        json_schema_extra={"label": "近期降权系数", "order": 19, "step": 0.1},
    )

    # —— 新增：分群策略 ——
    small_group_size: int = Field(
        default=30,
        description="小于该人数的群：纯均匀随机，不做过多的过滤与去重。",
        json_schema_extra={"label": "小群人数阈值", "order": 20, "step": 1},
    )
    large_group_size: int = Field(
        default=100,
        description="大于该人数的群：启用完整策略（过滤 + 去重）。",
        json_schema_extra={"label": "大群人数阈值", "order": 21, "step": 1},
    )
    min_candidates: int = Field(
        default=3,
        description="候选少于该数量时自动放宽过滤，避免抽不出人。",
        json_schema_extra={"label": "最少候选数", "order": 22, "step": 1},
    )
    group_overrides: Dict[str, Dict[str, object]] = Field(
        default_factory=dict,
        description="按群覆盖配置，例如 { \"123456\": { \"weight_mode\": \"uniform\" } }。",
        json_schema_extra={"label": "分群覆盖", "order": 23},
    )
    member_cache_seconds: int = Field(
        default=30,
        description="群成员列表缓存秒数，避免每条指令都拉全量成员。",
        json_schema_extra={"label": "成员缓存（秒）", "order": 24, "step": 5},
    )

    # —— 新增：观测 ——
    shadow_mode: bool = Field(
        default=False,
        description="影子模式：结果仍按旧的均匀随机，只在日志里输出新策略的统计。",
        json_schema_extra={"label": "影子模式", "order": 30},
    )
    verbose_log: bool = Field(
        default=True,
        description="每次抽取输出一行结构化 INFO 日志。",
        json_schema_extra={"label": "详细日志", "order": 31},
    )


class WifePickerConfig(PluginConfigBase):
    """插件配置总览。"""

    plugin: PluginSection = Field(default_factory=PluginSection)
    wife_picker: WifePickerSection = Field(default_factory=WifePickerSection)
