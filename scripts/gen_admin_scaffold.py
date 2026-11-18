#!/usr/bin/env python3
"""从页面清单真值源生成管理端的 page.tsx 与 api route.ts。

**为什么要生成**：D-21 结构断言要求「页数 = section 数 = 导航项数 = 路由键数」
四者相等。手工维护 11 份 page.tsx + 11 份 route.ts 必然数量漂移，
因此从 `web/app/admin/lib/pages.ts` 这**唯一真值源**批量生成。

本脚本**不自己维护页面清单** —— 它解析 pages.ts 的 ADMIN_PAGES 数组，
拿到 id / label / req 后再生成文件。清单改一处 → 重跑本脚本 → 全量同步。

用法：
    python3 scripts/gen_admin_scaffold.py --root web
    python3 scripts/gen_admin_scaffold.py --root web --check   # 只查不写（CI 用）
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# ── 真值源解析 ────────────────────────────────────────────────────────

ENTRY_RE = re.compile(
    r"\{\s*id:\s*\"(?P<id>[^\"]+)\"\s*,\s*"
    r"label:\s*\"(?P<label>[^\"]+)\"\s*,\s*"
    r"group:\s*\"(?P<group>[^\"]+)\"\s*,\s*"
    r"icon:\s*\"(?P<icon>[^\"]+)\"\s*,\s*"
    r"title:\s*\"(?P<title>[^\"]+)\"\s*,\s*"
    r"subtitle:\s*\"(?P<subtitle>[^\"]+)\"\s*,\s*"
    r"req:\s*\"(?P<req>[^\"]+)\"\s*,\s*\}",
    re.DOTALL,
)

ARRAY_RE = re.compile(
    r"export const ADMIN_PAGES[^=]*=\s*\[(?P<body>.*?)\]\s*as const", re.DOTALL
)


def read_pages(pages_ts: str) -> list[dict[str, str]]:
    """从 pages.ts 解析页面清单（真值源）。"""
    with open(pages_ts, encoding="utf-8") as f:
        text = f.read()
    m = ARRAY_RE.search(text)
    if not m:
        sys.exit(f"❌ 未能从 {pages_ts} 解析 ADMIN_PAGES 数组")
    out = [d.groupdict() for d in ENTRY_RE.finditer(m.group("body"))]
    if not out:
        sys.exit(f"❌ {pages_ts} 的 ADMIN_PAGES 为空")
    return out


# ── 模板 ──────────────────────────────────────────────────────────────

PAGE_TPL = '''import {{ AdminShell }} from "../components/AdminShell";
import {{ PageBody }} from "../components/PageBody";

/** {title}（`#{pid}` · {req}） */
export default function Page() {{
  return (
    <AdminShell active="{pid}">
      <section id="{pid}">
        <PageBody pageId="{pid}" />
      </section>
    </AdminShell>
  );
}}
'''

OVERVIEW_PAGE_TPL = '''"use client";

import {{ useCallback, useEffect, useState }} from "react";
import {{ AdminShell }} from "../components/AdminShell";
import {{ Overview }} from "../components/Overview";
import type {{ OverviewPayload }} from "../lib/data";

/** 概览 Dashboard（`#overview` · AD-09） */
export default function Page() {{
  const [data, setData] = useState<OverviewPayload | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {{
    try {{
      const res = await fetch("/api/overview", {{ cache: "no-store" }});
      if (!res.ok) throw new Error(String(res.status));
      setData((await res.json()) as OverviewPayload);
      setFailed(false);
    }} catch {{
      // 接口失败 → 骨架 + 重试，绝不显示 0 值
      setData(null);
      setFailed(true);
    }}
  }}, []);

  useEffect(() => {{
    void load();
  }}, [load]);

  return (
    <AdminShell active="overview">
      <section id="overview">
        <Overview
          stamp={{data?.stamp ?? null}}
          l1={{data?.l1 ?? null}}
          failed={{failed || data === null}}
          onRetry={{load}}
        />
      </section>
    </AdminShell>
  );
}}
'''

ROUTE_TPL = '''import {{ NextResponse }} from "next/server";

import {{ fetchOverview, toPayload }} from "../../../app/admin/lib/data";

/** {title} 数据接口（`#{pid}` · {req}） */
export async function GET() {{
  return NextResponse.json(toPayload(await fetchOverview()));
}}
'''


def fail(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="web", help="web 目录")
    ap.add_argument("--check", action="store_true", help="只查不写（CI 用）")
    a = ap.parse_args()

    admin = os.path.join(a.root, "app", "admin")
    api = os.path.join(a.root, "app", "api")
    pages_ts = os.path.join(admin, "lib", "pages.ts")
    if not os.path.exists(pages_ts):
        fail(f"真值源不存在：{pages_ts}")

    pages = read_pages(pages_ts)
    writes: dict[str, str] = {}
    problems: list[str] = []

    for p in pages:
        pid, title, req = p["id"], p["title"], p["req"]

        # ---- page.tsx ----
        tpl = OVERVIEW_PAGE_TPL if pid == "overview" else PAGE_TPL
        writes[os.path.join(admin, pid, "page.tsx")] = tpl.format(pid=pid, title=title, req=req)

        # ---- api route.ts ----
        writes[os.path.join(api, pid, "route.ts")] = ROUTE_TPL.format(pid=pid, title=title, req=req)

    for path, content in writes.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        cur = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                cur = f.read()
        if cur == content:
            continue
        if a.check:
            problems.append(
                f"内容与生成器不一致：{path}" if cur is not None else f"缺失（应由生成器产出）：{path}"
            )
            continue
        # 生成模式：内容有差异就重写（生成器是唯一产出通道，手改必被覆盖）
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

    if a.check:
        if problems:
            for p in problems:
                print(f"  ✗ {p}")
            fail(
                f"脚手架与生成器不一致（{len(problems)} 处）——"
                f"跑 `python3 scripts/gen_admin_scaffold.py --root {a.root}` 修复"
            )
        print(f"✓ 脚手架与生成器一致：{len(pages)} 个页面 + {len(pages)} 个路由")
        return 0

    # ---- D-21 四数一致自检（与 spec_lint 同口径：集合相等） ----
    truth = {p["id"] for p in pages}
    page_ids = {d for d in os.listdir(admin) if os.path.exists(os.path.join(admin, d, "page.tsx"))}
    route_ids = {d for d in os.listdir(api) if os.path.exists(os.path.join(api, d, "route.ts"))}
    section_ids: set[str] = set()
    for dp, dn, fn in os.walk(admin):
        dn[:] = [d for d in dn if d not in ("__pycache__", "node_modules")]
        for f in fn:
            if f.endswith(".tsx"):
                with open(os.path.join(dp, f), encoding="utf-8") as fh:
                    section_ids.update(re.findall(r'<section\s+id="([^"]+)"', fh.read()))

    sets = {"truth": truth, "pages": page_ids, "sections": section_ids, "routes": route_ids}
    for name, got in sets.items():
        if got != truth:
            fail(
                f"D-21 集合不一致 [{name}]：真值源 {len(truth)} 项 / 该项 {len(got)} 项；"
                f"多 {sorted(got - truth)}，少 {sorted(truth - got)}"
            )
    print(f"✓ 生成完成（{len(pages)} 页面 + {len(pages)} 路由），D-21 集合一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
