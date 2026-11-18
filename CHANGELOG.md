# 变更日志

## 1.0.1 — 2026-11-18

- **拆分白名单语义**：
  - `no_limit_users` 保持「不受每日一次限制」（每次触发都重抽）；
  - 新增 `unlimited_divorce_users`：只放开离婚次数限制，抽取行为仍是「当天固定 + 复读」。
- 修复：配置 `weight_mode = "uniform"` 时，大群仍会走加权逻辑的问题。

## 1.0.0 — 2026-11-18

基于 [whitefox/wife_picker](https://github.com/whitefox20011120/wife_picker) 2.0.1 的首个增强版本。

### 新增

- **活跃度过滤**：默认排除 7 天以上未发言的成员（依据成员列表的 `last_sent_time`）
- **手工黑名单**：`exclude_users` 可排除老板号、测试号
- **机器人排除**：支持成员的 `is_robot` 标记
- **同群当日去重**：同一天同一群不重复抽到同一个人（候选耗尽时自动放开）
- **近期降权**：最近 3 天被抽中过的人权重乘以 0.3（最低仍按 1.0）
- **群规模自适应**：小群纯随机、中群过滤、大群严格
- **可选加权抽样**：`weight_mode = "weighted"` 时按活跃度加权，默认 `uniform`
- **分群覆盖**：`group_overrides` 可对单个群单独设置策略
- **影子模式**：结果保持旧逻辑，只在日志输出新策略统计
- **成员列表缓存**：默认 30 秒，避免每条指令拉全量成员
- **按群异步锁**：并发抽奖不会抽到同一个人
- **结构化日志**：每次抽取记录总人数、活跃数、过滤后人数、策略、耗时、降级原因

### 保持不变

- `/今日老婆`、`/离婚` 的指令行为、文案、冷却、白名单逻辑与上游一致
- 配置字段名（`exclude_self` / `exclude_sender` / `bot_qq` / `no_limit_users` / `tz_offset_hours` /
  `send_avatar` / `avatar_size` / `cooldown_seconds` / `persist_enabled`）与上游相同
- 数据文件格式兼容上游，新增的 `picked_history` 缺失时自动补齐

### 数据文件

- 文件名改为 `data/wife_picker_plus_seen.json`，与上游的 `wife_picker_seen.json` 互不干扰
