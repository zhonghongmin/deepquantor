"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminShell } from "../components/AdminShell";
import { Overview } from "../components/Overview";
import type { OverviewPayload } from "../lib/data";

/** 概览 Dashboard（`#overview` · AD-09） */
export default function Page() {
  const [data, setData] = useState<OverviewPayload | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    try {
      const res = await fetch("/api/overview", { cache: "no-store" });
      if (!res.ok) throw new Error(String(res.status));
      setData((await res.json()) as OverviewPayload);
      setFailed(false);
    } catch {
      // 接口失败 → 骨架 + 重试，绝不显示 0 值
      setData(null);
      setFailed(true);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AdminShell active="overview">
      <section id="overview">
        <Overview
          stamp={data?.stamp ?? null}
          l1={data?.l1 ?? null}
          failed={failed || data === null}
          onRetry={load}
        />
      </section>
    </AdminShell>
  );
}
