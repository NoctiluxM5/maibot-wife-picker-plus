# 发布前必读（PUBLISHING）

这个目录是**脱敏后的公开版本**，可以直接推送到 GitHub。
推送前需要把 3 个占位符换成你自己的信息。

## 1. 需要替换的占位符

| 占位符 | 出现位置 | 换成 |
|---|---|---|
| `NoctiluxM5` | `_manifest.json`（id、author、urls）、README、ATTRIBUTION、LICENSE | 你的 GitHub 用户名 |
| `NoctiluxM5` | `LICENSE`、`ATTRIBUTION.md` | 你的名字或 ID |
| `https://github.com/NoctiluxM5/...` | `_manifest.json`、README | 你的仓库地址 |

**注意**：`_manifest.json` 里的 `id` 一旦发布就会被插件中心记录，之后不要改。
建议用 `github.你的用户名.wife-picker-plus` 这种格式。

## 2. 发布步骤

```bash
# ① 建仓库后推送
git init -b main
git add -A
git commit -m "feat: 今日老婆 Plus 1.0.2"
git remote add origin https://github.com/NoctiluxM5/maibot-wife-picker-plus.git
git push -u origin main

# ② 打 tag 并发布 Release（必须，否则插件中心不收）
git tag v1.0.2
git push origin v1.0.2
# 然后到 GitHub 页面点 "Draft a new release"，选 v1.0.2，点 "Publish release"
```

## 3. 登记到官方插件中心

1. 打开 https://github.com/Mai-with-u/plugin-repo/issues/new/choose
2. 选 **"Add Plugin / 添加插件"** 模板
3. 按模板填写仓库地址、插件名、简介
4. 提交后等机器人校验；有问题会回复，修好后评论 `/recheck`

## 4. 检查清单

- [ ] 仓库是**公开**的
- [ ] 根目录**没有** `config.toml`（只有 `config.example.toml`）
- [ ] `_manifest.json` 的 `version` 与 Release tag 一致（`1.0.2` ↔ `v1.0.2`）
- [ ] `LICENSE` 存在且与 manifest 的 `license` 字段一致（MIT）
- [ ] Release 是**正式发布**，不是草稿、不是只有 tag
- [ ] 没有提交 `data/`（里面有运行时数据）

## 5. 上游致谢

本项目基于 [whitefox/wife_picker](https://github.com/whitefox20011120/wife_picker)（MIT），
原始版权声明保留在 `LICENSE` 与 `ATTRIBUTION.md`，请勿删除。
