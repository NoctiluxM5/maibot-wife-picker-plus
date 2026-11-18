# 💕 今日老婆 Plus（MaiBot 插件）

> 群友发 `/今日老婆`，从**本群活跃成员**里随机抽一位当今日老婆。
> 这是 [whitefox/wife_picker](https://github.com/whitefox20011120/wife_picker) 的增强分支：
> 在原有随机抽取的基础上，加入了**活跃度过滤、当日去重、群规模自适应**。

---

## 与上游的区别

| 特性 | 上游 2.0.1 | 本插件 1.0.2 |
|---|---|---|
| 每日固定结果 | ✅ | ✅ |
| 离婚重抽（每日一次） | ✅ | ✅ |
| 头像发送 | ✅ | ✅ |
| 白名单不受限 | ✅ | ✅ |
| **活跃度过滤**（自动排除长期潜水） | ❌ | ✅ 默认 7 天 |
| **同群当日去重**（不重复抽到同一人） | ❌ | ✅ |
| **近期降权**（前几天抽中过的人概率降低） | ❌ | ✅ |
| **群规模自适应**（小群纯随机 / 大群严格） | ❌ | ✅ |
| **加权抽样**（越活跃概率越高） | ❌ | ⚙️ 可选，默认关 |
| **影子模式**（上线前只记录不生效） | ❌ | ✅ |
| 成员列表缓存 | ❌ | ✅ 默认 30 秒 |
| 结构化抽取日志 | ❌ | ✅ |

> **为什么加权默认关**：「今日老婆」是整活指令，公平比效率重要。
> 默认所有人都等概率，只把「长期不说话的号」剔掉；需要时可以按群开启加权。

---

## 安装

把整个目录放进 MaiBot 的 `plugins/`：

```
plugins/
└── wife-picker-plus/
    ├── _manifest.json
    ├── plugin.py
    ├── sampling.py
    ├── utils.py
    ├── config.py
    └── config.toml        # 首次加载时自动生成
```

重启 MaiBot，或 WebUI → 插件管理 → 安装。

> ⚠️ **不要和上游的 `wife_picker` 同时启用**——两者都监听 `/今日老婆`，会抢答。
> 二选一：在配置里把不用的那个 `[plugin] enabled = false`。

---

## 命令

| 命令 | 说明 |
|---|---|
| `/今日老婆` | 抽今天的（每人每天固定，重复触发返回同一人） |
| `/离婚` | 清空今日记录，可重抽（每日仅一次） |

---

## 配置说明

首次加载会在插件目录生成 `config.toml`，也可在 WebUI 修改。
**原有字段名与上游一致**，老配置可以直接复制过来。

### `[wife_picker]` 原有配置

| 键 | 默认 | 说明 |
|---|---|---|
| `exclude_self` | `true` | 排除机器人自己 |
| `exclude_sender` | `true` | 排除发起人 |
| `bot_qq` | `""` | 机器人 QQ，留空自动获取 |
| `no_limit_users` | `[]` | **无限抽取**：不受「每天只能抽一次」限制，每次触发都重抽 |
| `unlimited_divorce_users` | `[]` | **无限离婚**：不受「每天只能离婚一次」限制，可反复 `/离婚` 重抽（推荐） |
| `tz_offset_hours` | `8` | 「今天」的时区偏移 |
| `send_avatar` | `true` | 是否发头像 |
| `avatar_size` | `640` | 头像尺寸 |
| `cooldown_seconds` | `60` | 同一指令冷却 |
| `persist_enabled` | `true` | 是否持久化 |

### 新增：过滤

| 键 | 默认 | 说明 |
|---|---|---|
| `exclude_users` | `[]` | 永久黑名单 QQ |
| `exclude_bots` | `true` | 排除标记为机器人的成员 |
| `min_active_days` | `7.0` | 超过 N 天没发言不参与；`0` = 关闭 |
| `min_join_days` | `0.0` | 入群不足 N 天不参与；`0` = 不限制 |

### 新增：抽样

| 键 | 默认 | 说明 |
|---|---|---|
| `weight_mode` | `"uniform"` | `uniform` 等概率 / `weighted` 越活跃权重越高 |
| `alpha` | `1.0` | 加权强度（仅 weighted 生效） |
| `max_weight` | `2.0` | 单人最大权重，防止话痨垄断 |

### 新增：去重

| 键 | 默认 | 说明 |
|---|---|---|
| `unique_per_day_per_group` | `true` | 同群同日不重复（候选不够时自动放开） |
| `recent_penalty_days` | `3.0` | 最近 N 天被抽中过的人降权 |
| `recent_penalty_factor` | `0.3` | 降权倍数（最低仍按 1.0） |

### 新增：分群策略

| 键 | 默认 | 说明 |
|---|---|---|
| `small_group_size` | `30` | 小于该人数：纯均匀随机，不去重 |
| `large_group_size` | `100` | 大于该人数：过滤 + 加权 + 去重 |
| `min_candidates` | `3` | 候选不足时自动放宽过滤 |
| `member_cache_seconds` | `30` | 成员列表缓存 |
| `group_overrides` | `{}` | 按群覆盖，见下 |

### 新增：观测

| 键 | 默认 | 说明 |
|---|---|---|
| `shadow_mode` | `false` | 结果仍走旧逻辑，只记录新策略统计 |
| `verbose_log` | `true` | 每次抽取输出一行结构化日志 |

---

## 按群覆盖

想让某个群特殊一点：

```toml
[wife_picker.group_overrides."123456789"]
weight_mode = "weighted"
unique_per_day_per_group = true
```

支持的覆盖字段与上面同名（`weight_mode` / `min_active_days` / `unique_per_day_per_group` / `small_group_size` / `large_group_size` / `min_candidates` 等）。

---

## 阈值参考

| 群规模 | 策略 | 说明 |
|---|---|---|
| < 30 人 | 纯均匀随机 | 人少，谁都认识，保留惊喜感 |
| 30 ~ 100 人 | 过滤死号 + 按配置抽样 | 默认仍是等概率 |
| > 100 人 | 过滤 + 去重 | 避免一天里反复抽到同一个人 |

**夜晚/冷清时段**候选变少时，会依次降级：放宽活跃过滤 → 放开去重 → 放弃加权。**任何情况下都不会抽不出人。**

---

## 上线建议

**第一步：影子模式跑一天**

```toml
shadow_mode = true
```

这时结果和旧版完全一样，但日志里会出现：

```
[shadow] 群=123456789 总成员=137 活跃=90 过滤后=85 策略=large:weighted+dedupe
         抽中=某某(123456) 用时=3.1ms 降级=无 前三占比=0.0
```

看几个群的数据，确认「过滤后还剩多少人」合理，再关掉影子模式。

**第二步：正式启用**

```toml
shadow_mode = false
weight_mode = "uniform"   # 保持公平
```

---

## 常见问题

**Q：为什么抽不到某个经常潜水的人？**

默认 `min_active_days = 7`，7 天没发言的人不参与。想让他参与就调大或设 `0`。

**Q：小群里怎么感觉和以前一样？**

小群（< 30 人）默认就是纯均匀随机、不去重，这是刻意设计——人少的时候惊喜感更重要。

**Q：一天里会不会抽到同一个老婆两次？**

大群（> 100 人）默认去重；小群为了保留池子不做去重。都可以通过配置调整。

**Q：怎么回滚到上游插件？**

把本插件 `enabled = false`，上游插件 `enabled = true`，重启即可。两个插件的数据文件是分开的。

**Q：接口不支持 `last_sent_time` 怎么办？**

会自动降级为「不按活跃度过滤」，并在日志里 WARN 一次，其余规则照常生效。

---

## 开发

```bash
# 抽样逻辑的单元测试（不依赖 MaiBot）
python -m unittest discover -s tests -v
```

`sampling.py` 是纯函数实现，不 import MaiBot，方便单独测试和复用。

---

## 许可与致谢

本项目基于 [whitefox/wife_picker](https://github.com/whitefox20011120/wife_picker)（MIT，Copyright © 2026 白狐）改造，
原版权声明与许可证完整保留，详见 [LICENSE](LICENSE) 与 [ATTRIBUTION.md](ATTRIBUTION.md)。

本分支的修改部分：Copyright © 2026 NoctiluxM5，同样以 MIT 协议发布。
