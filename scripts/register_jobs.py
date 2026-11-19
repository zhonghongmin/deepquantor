"""B3-a 登记脚本：幂等写 task.job_def，回写/保留 automation_id。

职责（Spec §2.1）：
- 读 deploy/scheduler/jobs.yaml（任务定义唯一权威），幂等 upsert 到 task.job_def；
- automation_id 由平台建任务后回写：已存在的 automation_id 不得被本脚本清掉；
- cron 守卫：任何 job 的 cron 落在 09:30–15:00 → 退出码 2，不写库（SC-02/06）；
- 幂等：重跑不产生重复行（job_key 主键 upsert）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

DEFAULT_JOBS_YAML = Path(__file__).resolve().parents[1] / "deploy" / "scheduler" / "jobs.yaml"

# 交易日 09:30–15:00 禁排（守卫只在本脚本与平台侧，CLI 不重复硬编码）
GUARD_START_MIN = 9 * 60 + 30   # 570
GUARD_END_MIN = 15 * 60         # 900


def parse_cron(expr: str) -> list[str]:
    """5 段标准 cron 解析（分 时 日 月 周），段数不符即 ValueError。"""
    parts = expr.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron 须为 5 段标准格式：{expr!r}")
    return parts


def cron_hits_trading_window(expr: str) -> bool:
    """cron 是否可能落在 09:30–15:00（按分钟与小时段交叉判定，工作日与每日字段不影响窗口命中）。"""
    minute, hour, _day, _month, _week = parse_cron(expr)

    def _expand(field: str, low: int, high: int) -> set[int]:
        vals: set[int] = set()
        for tok in field.split(","):
            step = 1
            if "/" in tok:
                tok, step_s = tok.split("/", 1)
                step = int(step_s)
            if tok == "*" or tok == "?":
                cand = range(low, high + 1)
            elif "-" in tok:
                a, b = tok.split("-")
                cand = range(int(a), int(b) + 1)
            else:
                cand = [int(tok)]
            vals.update(range(min(cand), max(cand) + 1, step) if len(cand) > 1 else cand)
        return {v for v in vals if low <= v <= high}

    hours = _expand(hour, 0, 23)
    minutes = _expand(minute, 0, 59)
    for h in hours:
        for m in minutes:
            t = h * 60 + m
            if GUARD_START_MIN <= t < GUARD_END_MIN:
                return True
    return False


def load_jobs(path: Path = DEFAULT_JOBS_YAML) -> list[dict]:
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    jobs = data.get("jobs") or []
    if not jobs:
        raise ValueError("jobs.yaml 无任务定义")
    return jobs


def _is_sqlite(conn) -> bool:
    return conn.__class__.__module__.startswith("sqlite3")


def _params_for(conn, job: dict):
    params = job.get("params")
    return None if params is None else json.dumps(params, ensure_ascii=False)


def upsert_job_defs(conn, jobs: list[dict]) -> tuple[int, int]:
    """幂等 upsert task.job_def；已登记 automation_id 一律保留。返回 (新增, 更新)。"""
    ph = "?" if _is_sqlite(conn) else "%s"
    updated_at = "CURRENT_TIMESTAMP" if _is_sqlite(conn) else "now()"
    inserted = updated = 0
    for j in jobs:
        parse_cron(j["cron_expr"])
        cur = conn.cursor()
        cur.execute(f"SELECT 1 FROM task.job_def WHERE job_key = {ph}", (j["job_key"],))
        exists = cur.fetchone() is not None
        if exists:
            # 保留 automation_id 与 updated_by 审计
            cur.execute(
                f"UPDATE task.job_def SET job_name={ph}, freq={ph}, cron_expr={ph},"
                f" cli_command={ph}, params_json={ph}, retry_cnt={ph}, timeout_sec={ph},"
                f" enabled={ph}, updated_at={updated_at} WHERE job_key={ph}",
                (j["job_name"], j["freq"], j["cron_expr"], j["cli_command"],
                 _params_for(conn, j), j.get("retry_cnt", 3), j.get("timeout_sec", 1800),
                 j.get("enabled", True), j["job_key"]),
            )
            updated += 1
        else:
            cur.execute(
                f"INSERT INTO task.job_def (job_key, job_name, freq, cron_expr, cli_command,"
                f" params_json, retry_cnt, timeout_sec, enabled)"
                f" VALUES ({ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph}, {ph})",
                (j["job_key"], j["job_name"], j["freq"], j["cron_expr"], j["cli_command"],
                 _params_for(conn, j), j.get("retry_cnt", 3), j.get("timeout_sec", 1800),
                 j.get("enabled", True)),
            )
            inserted += 1
    conn.commit()
    return inserted, updated


def register(conn, path: Path = DEFAULT_JOBS_YAML) -> tuple[int, int]:
    """主流程：加载 → cron 守卫（违规退出码 2）→ 幂等 upsert。"""
    jobs = load_jobs(path)
    violations = [j["job_key"] for j in jobs if cron_hits_trading_window(j["cron_expr"])]
    if violations:
        raise CronGuardViolation(
            f"cron 落在 09:30–15:00 交易窗口，禁止登记：{', '.join(violations)}（退出码 2）"
        )
    return upsert_job_defs(conn, jobs)


class CronGuardViolation(RuntimeError):
    """cron 守卫违规（对应 CLI 退出码 2）。"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="register_jobs")
    p.add_argument("--jobs-yaml", default=str(DEFAULT_JOBS_YAML))
    args = p.parse_args(argv)
    conn = sys.modules.get("__dq_register_conn__")  # 测试注入；生产由 psycopg2 接线
    if conn is None:
        import psycopg2

        from dq.data.credentials import load_credentials
        creds = load_credentials()
        conn = psycopg2.connect(
            host=creds["AD_HOST"], port=creds["AD_PORT"], user=creds["AD_USER"],
            dbname="deepquantor", password=creds.get("AD_TOKEN", ""),
        )
    try:
        ins, upd = register(conn, Path(args.jobs_yaml))
        print(f"job_def 登记：新增 {ins}，更新 {upd}")
        return 0
    except CronGuardViolation as e:
        print(str(e))
        return 2
    except Exception as e:  # noqa: BLE001 —— 登记失败须显式非零退出
        print(f"登记失败：{type(e).__name__}: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
