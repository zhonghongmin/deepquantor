# deepquantor · 量化选股系统

代码库（git 管理）。文档真值在**项目资产**（网盘目录 `CEgKZcgndFHV`），本仓库只放代码与可执行资产。

> 原则：同一事实只写一处。文档 → 项目资产；代码 → 本仓库；派生视图（HTML 阅读版）→ 实时渲染，不入库。

## 目录结构

```
deepquantor/
├── cli/                      # Python 3.11 线下采集与计算（包名 dq）
│   ├── dq/
│   │   ├── cli.py            #   统一入口 python -m dq.cli <job_key>
│   │   ├── collectors/       #   按数据源分目录 fetch → transform → persist（自注册）
│   │   ├── schemas/          #   字段定义与类型（对齐《数据库设计文档》）
│   │   ├── config/           #   只从 env 读，不硬编码阈值
│   │   └── macro/            #   宏观策略引擎（纯函数 + 总装配）
│   ├── tests/                #   pytest 单测 + 数据口径校验
│   ├── pyproject.toml
│   └── requirements.lock     #   依赖锁（uv pip compile 生成，禁止手改）
├── web/                      # Node 22 + Next.js + Tailwind 线上站点（管理端）
│   ├── app/api/<resource>/route.ts
│   ├── app/admin/<page>/page.tsx
│   ├── lib/<domain>.ts
│   ├── services/db.ts        #   只读线上结果副本 + 用户域写
│   └── tests/{unit,integration}/
├── deploy/                   # 部署侧（文档 §4）
│   ├── env/                  #   .env.example 模板（实际 .env 不入库）
│   ├── postgres/             #   ddl.sql 唯一可执行权威 + 分域授权
│   ├── redis/
│   ├── scheduler/            #   jobs.yaml 任务定义唯一权威
│   ├── sync/                 #   两个 sync-* CLI（双库唯一通道）
│   └── scripts/              #   bootstrap / start / backup / healthcheck
├── spec/                     # 单一事实源（D-21 §14.3）
│   ├── invariants.yaml       #   受检文件登记 / 禁用词 / 结构断言 / 计数规则
│   ├── decisions.yaml        #   决议登记（status / affects / tests）
│   ├── pages.yaml            #   页面清单（L2）
│   ├── schema.yaml           #   表清单与字段口径（L2）
│   └── terms.yaml            #   术语词典（L2）
├── migrations/               #   YYYYMMDD_xxx.sql（必须配 .rollback.sql）
├── scripts/
│   ├── spec_lint.py          #   一致性门禁
│   └── init-repo.ps1         #   Windows 本地仓库初始化脚本
└── .github/workflows/ci.yml  #   CI 门禁
```

## 依赖方向红线

```
Node:   route → lib → services → 线上 DB
Python: CLI 入口 → collectors → schemas → config → 线下 DB
```

- 线上不直连线下库、不执行采数与策略计算、不实时调模型
- 双库唯一通道是 `sync-*` CLI，线上不得反向连接线下
- 规则与计算是纯函数，I/O 在外层注入，便于 mock

## 凭证边界

`.env` **不入版本库**（NFR-07）。数据源凭证、模型凭证只在 offline-node；线上库不保存线下库地址与账号。
模板见 `deploy/env/.env.example`。

## 本地初始化（Windows）

```powershell
cd D:\develop\deepquantor
.\scripts\init-repo.ps1 -Remote https://git.woa.com/<group>/deepquantor.git
```

脚本幂等，重复执行安全；不改全局 git 配置；提交前会拦截误暂存的 `.env`。

装依赖（内网 PyPI 慢，务必用清华源）：

```powershell
cd cli
uv venv --python 3.11
uv pip install -e ".[dev]" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
uv pip compile pyproject.toml -o requirements.lock --index-url https://pypi.tuna.tsinghua.edu.cn/simple

cd ..\web
npm install
```

## 提交前门禁

```bash
python scripts/spec_lint.py --spec spec/ --root .   # 一致性门禁（CI 必跑）
cd cli && pytest -v                                  # 单测
cd web && npm test                                   # 单测
```

CI 必过项：`spec_lint` / `ruff` / `pytest`（覆盖率 ≥80%）/ `tsc --noEmit` / `next lint` / `vitest` / `next build` / 迁移回滚脚本配对。

## 表结构变更纪律

唯一可执行权威 = `数据库DDL.sql`（项目资产）。变更顺序：**先 DDL → 再库设计文档 → 最后代码**。
迁移走 `migrations/YYYYMMDD_xxx.sql` + 同名 `.rollback.sql`，缺一 CI 失败。

## 相关文档（项目资产，不在本仓库）

《量化选股系统·需求文档》/《系统设计总文档》/《数据库设计文档》/《数据策略总文档》/《环境与初始化文档》/《决策登记》/《需求与Bug追踪》
