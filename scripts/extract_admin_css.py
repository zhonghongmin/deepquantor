#!/usr/bin/env python3
"""从《管理端效果图.html》抽取管理端用到的 CSS，生成 `web/app/admin/admin.css`。

**为什么脚本化**：视觉基线要求 CSS 变量与取值「逐值一致」于效果图。
手抄 30+ 条规则必然漂移（改色值、漏 border-radius），故直接抽取。

规则集白名单化：只抽管理端真实用到的选择器，避免把 381KB 效果图整份搬进来。
`--extensions` 部分是效果图里没有、但需求文档 P1 要求的样式（骨架 / 重试 / 占位页），
在文件里显式标注「需求增补」，与「效果图抽取」两段分开，便于审计。

用法：
    python3 scripts/extract_admin_css.py --effect <效果图.html> --out web/app/admin/admin.css
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# 管理端真实用到的选择器（与效果图一致）
WANTED = [
    ":root",
    "*",
    "body",
    "@keyframes fade",
    ".app", ".side", ".brand", ".brand img", ".brand b", ".brand small",
    ".nav", ".nav .grp", ".nav a", ".nav a:hover", ".nav a.active", ".nav a .ic",
    ".side-foot", ".side-foot div", ".side-foot div small", ".side-foot .av",
    ".main", ".topbar", ".topbar .tleft", ".topbar .right", ".topbar .right .dot",
    ".crumb", ".crumb b", ".crumb span",
    ".btn", ".btn.ghost", ".btn.sm", ".btn:disabled",
    ".content", ".section", ".section.show",
    ".page-h", ".page-h h2", ".page-h p",
    ".pill", ".mono", ".dot",
    ".layer-row", ".layer", ".layer.on", ".layer.off",
    ".layer .lhd", ".layer .lnum", ".layer.on .lnum", ".layer .lhd b",
    ".layer.off .lhd b", ".layer .lhd .tag",
    ".layer .lbody", ".layer .lbody.mute", ".layer .li", ".layer .li b",
    ".layer .li b.green", ".layer .li b.amber", ".layer .li span",
    ".layer .lfoot", ".layer .lfoot .lk",
    ".tag", ".tag.ok", ".tag.warn", ".tag.bad", ".tag.gray", ".tag.blue",
    ".stat-strip", ".stat-strip .it", ".stat-strip .n", ".stat-strip .n.green",
    ".stat-strip .n.amber", ".stat-strip .n.red", ".stat-strip .dot",
    ".stat-strip .dot.ok", ".stat-strip .dot.warn", ".stat-strip .dot.bad",
    ".stat-strip .vline", ".stat-strip .tip",
]

WANTED_SET = set(WANTED)

EXTENSIONS = """
/* ============================================================
 * 需求增补段（效果图里没有，但需求文档 §5.9.3 P1 明确要求）
 * ============================================================ */

/* 接口失败：三层卡显骨架，不显示 0 值（0 与失败必须可区分） */
.skeleton {
  background: linear-gradient(90deg, var(--line2) 25%, #f7f9fb 50%, var(--line2) 75%);
  background-size: 400% 100%;
  animation: shimmer 1.4s ease infinite;
  border-radius: 6px;
  color: transparent;
  user-select: none;
}

@keyframes shimmer {
  0% { background-position: 100% 0; }
  100% { background-position: 0 0; }
}

.retry {
  margin-top: 10px;
  font-size: 12.5px;
}

.retry button {
  border: 1px solid var(--line);
  background: var(--panel);
  color: var(--blue);
  border-radius: 8px;
  padding: 5px 12px;
  font-size: 12.5px;
  cursor: pointer;
}

.retry button:hover { background: var(--blue-soft); }

/* 未实现页占位（骨架屏）：说明「待实现」而非留白 */
.todo-card {
  background: var(--panel);
  border: 1px dashed var(--line);
  border-radius: 14px;
  padding: 22px 24px;
}

.todo-card h3 {
  margin: 0 0 8px;
  font-size: 15px;
  color: var(--navy);
}

.todo-card p {
  margin: 0 0 6px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.7;
}

.todo-card .req {
  display: inline-block;
  margin-top: 6px;
  padding: 2px 8px;
  border-radius: 6px;
  background: var(--blue-soft);
  color: var(--blue);
  font-size: 11.5px;
  font-weight: 600;
}
"""


def _iter_rules(css: str):
    """产出 (media_query, selector, body)。

    按大括号深度**递归**解析，支持嵌套 @media。
    （早期版本用正则剥离 @media，嵌套时会把中间的顶层规则一起吞掉 ——
      `.side` 的深蓝背景就是这样丢的。此处改为逐字符配平大括号。）
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)  # 去注释
    i = 0
    n = len(css)
    while i < n:
        # 跳过空白与残留的分号
        while i < n and css[i].isspace():
            i += 1
        if i >= n:
            break
        j = css.find("{", i)
        if j < 0:
            break
        prelude = css[i:j].strip()
        # 配平大括号，取块内容
        depth = 1
        k = j + 1
        while k < n and depth:
            if css[k] == "{":
                depth += 1
            elif css[k] == "}":
                depth -= 1
            k += 1
        inner = css[j + 1 : k - 1]

        if prelude.startswith("@media"):
            query = "@media" + prelude[len("@media") :].strip()
            for q2, sel, body in _iter_rules(inner):
                yield f"{query} {q2}".strip(), sel, body
        elif prelude.startswith("@keyframes"):
            yield "", prelude, inner
        elif prelude.startswith("@"):
            # 其他 at-rule（@supports / @font-face 等）暂不抽取
            pass
        else:
            # 普通样式规则：prelude 就是选择器，inner 就是声明
            sel = " ".join(prelude.split())
            if sel:
                yield "", sel, " ".join(inner.split())
        i = k


def _iter_plain(css: str):
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = " ".join(m.group(1).split())
        body = " ".join(m.group(2).split())
        if sel.startswith("@") or not sel:
            continue
        yield sel, body


def _keep(sel: str) -> bool:
    """选择器是否命中白名单。

    白名单按「单选择器」匹配：`.nav a.active` 这类组合写法需逐条登记，
    否则整条规则会被丢弃 —— 白名单是显式的，不用前缀通配。
    """
    return any(p.strip() in WANTED_SET for p in sel.split(","))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--effect", required=True, help="管理端效果图.html 路径")
    ap.add_argument("--out", required=True, help="输出 CSS 路径")
    a = ap.parse_args()

    eff = Path(a.effect)
    if not eff.exists():
        print(f"效果图不存在：{eff}", file=sys.stderr)
        return 2
    html = eff.read_text(encoding="utf-8")
    m = re.search(r"<style[^>]*>(.*?)</style>", html, re.DOTALL)
    if not m:
        print("效果图里没有 <style> 块", file=sys.stderr)
        return 2
    css = m.group(1)

    kept: list[str] = []
    media: dict[str, list[str]] = {}
    for query, sel, body in _iter_rules(css):
        if sel.startswith("@keyframes"):
            # 动画定义整体保留（.section 的淡入等）
            if sel in WANTED_SET:
                kept.append(f"{sel} {{ {body} }}")
            continue
        if not _keep(sel):
            continue
        rule = f"{sel} {{ {body} }}"
        if query:
            media.setdefault(query, []).append(rule)
        else:
            kept.append(rule)

    header = """/**
 * 管理端视觉基线 —— **由脚本从效果图抽取，勿手改**。
 *
 * 生成命令：
 *     python3 scripts/extract_admin_css.py \\
 *         --effect <《管理端效果图.html》> \\
 *         --out web/app/admin/admin.css
 *
 * 口径来源：需求文档 §5.0「视觉与展示规范」——配色、字体、圆角、间距一律以
 * `管理端效果图.html` 为准。改色值必须先改效果图，再重跑本脚本。
 *
 * 本文件分两段：
 *   1) 效果图抽取段（下方）—— 选择器与取值均与效果图逐值一致
 *   2) 需求增补段 —— 效果图没有、但需求文档 P1 要求（骨架 / 重试 / 占位页）
 */

"""

    body_out = "\n".join(kept)
    media_out = ""
    if media:
        media_out = "\n/* ---------- 效果图抽取段 · 响应式 ---------- */\n"
        for query in sorted(media):
            media_out += f"\n{query}{{\n" + "\n".join(media[query]) + "\n}\n"

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(header + body_out + "\n" + media_out + EXTENSIONS, encoding="utf-8")

    print(f"✓ 抽取 {len(kept)} 条规则 + {len(media)} 组响应式 → {out}")
    print(f"  白名单选择器 {len(WANTED_SET)} 个，未命中即视为遗漏，需回补脚本")
    return 0


if __name__ == "__main__":
    sys.exit(main())
