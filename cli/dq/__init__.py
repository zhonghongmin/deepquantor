"""dq —— 量化选股系统 · 线下采集与计算 CLI 包。

职责边界（依赖方向红线：CLI 入口 → collectors → schemas → config → 线下 DB）：
  - `dq.cli`     ：统一入口 `python -m dq.cli <job_key> --window-date ... --run-id ...`
  - `dq.collectors/<source>/`：按数据源分目录，fetch → transform → persist，自注册
  - `dq.schemas/`：字段定义与类型（与《数据库设计文档》对齐）
  - `dq.config`  ：只从环境变量 / .env 读取，不硬编码阈值
  - `dq.macro`   ：宏观策略引擎（纯函数 + 总装配）

约束：规则与计算是纯函数，I/O 在外层注入，便于 mock。
"""

__version__ = "0.1.0"
