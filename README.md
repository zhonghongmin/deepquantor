# deepquantor · 量化选股系统

代码基座（git 管理）。**当前为治理空壳**：早期生成的代码（宏观引擎 / 前端骨架 / 同步脚本）口径过期、与项目资产文档不一致，已于 2026-11-18 清除。开发在本地基座 `D:\develop\deepquantor` 接续，不在沙箱进行（决策 E-07）。

> 真值边界：**文档与需求状态 → 项目资产（网盘 `CEgKZcgndFHV`）**；代码 → 本地基座。同一事实只写一处，不互相镜像。
> 一切以项目资产文档为准；本仓库 README 与 `docs/` 下的历史操作记录仅供参考，与项目资产冲突时以项目资产为准。

## 当前保留内容

```
deepquantor/
├── spec/
│   ├── invariants.yaml        # 不变量框架（禁用词 / 受控词 / 冲突对 / 计数规则）
│   └── decisions.yaml         # 决议登记（当前仅 D-21 治理本体）
├── scripts/
│   ├── spec_lint.py           # 一致性门禁（D-21）
│   ├── restore-git-credential.sh  # Deploy Key 恢复（幂等）
│   └── push-github.sh         # 推送回验
├── docs/                      # 历史操作记录（可能过期，以项目资产为准）
└── .github/workflows/ci.yml   # CI：仅保留 spec_lint 门禁
```

受检文件登记 `files: []` 与结构断言 `structure_assertions: []` 当前为空——本地重建代码时须按 `spec_lint` 纪律同步登记，否则判为「无主漂移」。

## 门禁

```bash
python scripts/spec_lint.py --spec spec/ --root .   # 一致性门禁（唯一在跑的门禁）
```

`pytest` / `ruff` / `vitest` / `tsc` / 迁移回滚配对等门禁待本地代码重建后恢复（见 `dq-deploy-skill` 的 `git-workflow.md` §4）。

## 凭据

仓库级 Deploy Key，私钥托管在项目资产 `.agent-credentials`（file_id `CJukhqAlcBCS`），不入库。换机 / 沙箱重建后：

```bash
# 由 agent 签发直链后调用恢复脚本（勿手写直链）
bash scripts/restore-git-credential.sh <download_url>
```

`.env` 不入版本库（NFR-07）。

## 提交约定

Conventional Commits；分支 `feature/<需求ID>-<简述>`，需求 ID 取自《需求与Bug追踪》；文档与代码同 PR；推送后回验 SHA。细则见 `dq-deploy-skill` 的 `references/git-workflow.md`。

## 相关文档（唯一真值，项目资产，不在本仓库）

《需求文档》/《需求与Bug追踪》/《决策登记》/《系统设计总文档》/《数据策略总文档》/《数据库设计文档》/《数据库DDL.sql》/《环境与初始化文档》
