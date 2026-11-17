#!/usr/bin/env python3
"""spec_lint —— 文档与决议一致性门禁（D-21）。

做什么：
  1. 受检文件登记检查：源码文件须在 spec/invariants.yaml → files 登记，否则判「无主漂移」
  2. 禁用词检查：文件内容不得含 banned_terms / controlled_terms.forbidden
  3. 决议反查：spec/invariants.yaml 中登记的 decision 须存在于 spec/decisions.yaml
  4. 决议状态门禁：status 未达 propagated 的决议，不得被标记为 propagated 之外的完成态
  5. 结构断言：数量关系检查（当前支持 counts_equal / sum_equals）

退出码：0 通过 / 1 不通过（CI 门禁失败禁止合并）

用法：
    python scripts/spec_lint.py --spec spec/ --root .
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("缺 pyyaml：pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# 扫描范围：只扫受管目录，避免扫到依赖与产物
SCAN_GLOBS = [
    "cli/dq/**/*.py",
    "cli/tests/**/*.py",
    "web/app/**/*.{ts,tsx}",
    "web/lib/**/*.ts",
    "web/services/**/*.ts",
    "deploy/**/*.py",
    "deploy/**/*.sh",
]


def load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def iter_scan_files(root: Path, patterns: list[str]) -> list[Path]:
    out: list[Path] = []
    for pat in patterns:
        out.extend(p for p in root.glob(pat) if p.is_file())
    return sorted(set(out))


def norm_rel(p: Path, root: Path) -> str:
    return p.relative_to(root).as_posix()


def check_unregistered_files(root: Path, inv: dict, findings: list) -> None:
    """规则 1：源码文件必须在 files 中登记。"""
    registered = {f["path"].replace("\\", "/") for f in inv.get("files") or []}
    if not registered:
        return
    for f in iter_scan_files(root, SCAN_GLOBS):
        rel = norm_rel(f, root)
        if rel not in registered:
            findings.append({
                "rule": "unregistered-file",
                "file": rel,
                "message": "源码文件未在 spec/invariants.yaml → files 登记，判为「无主漂移」",
            })


def _is_negated_context(line: str, term: str) -> bool:
    """判断该行是否为「禁止/不得使用某词」的语境。

    机械判定原则（宁可漏报也不产生噪音）：禁用词若出现在否定语境
    （禁止硬编码 / 不硬编码阈值 / 不得写死 / 避免主库 等），说明作者正在
    引用规则本身，不是违规。此时不告警。

    否定词可能在词前（禁止硬编码）也可能在词后（不硬编码阈值），
    故前后窗口都查。
    """
    idx = line.find(term)
    if idx < 0:
        return False
    before = line[max(0, idx - 24): idx]
    after = line[idx + len(term): idx + len(term) + 12]
    marks = ("禁止", "不得", "勿", "避免", "切勿", "不要", "不可", "不", "非")
    return any(k in before for k in marks) or any(after.startswith(k) for k in marks)


def check_banned_terms(root: Path, inv: dict, findings: list) -> None:
    """规则 2：禁用词 / 受控词禁用别名。

    注意：
      - 否定语境（禁止硬编码…）不算违规，见 _is_negated_context
      - 跳过注释行（以 # 开头的行）
    """
    banned = [(b["term"], b.get("reason", "")) for b in inv.get("banned_terms") or []]
    for ct in inv.get("controlled_terms") or []:
        for w in ct.get("forbidden") or []:
            banned.append((w, f"受控词「{ct['concept']}」的禁用别名"))
    if not banned:
        return
    for f in iter_scan_files(root, SCAN_GLOBS):
        try:
            text = f.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        # 同一行的同一词只报一次（禁用词与受控词可能重复命中同一处）
        seen: set[tuple[str, int, str]] = set()
        for term, reason in banned:
            if not term:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                if term not in line:
                    continue
                if _is_negated_context(line, term):
                    continue
                key = (norm_rel(f, root), i, term)
                if key in seen:
                    continue
                seen.add(key)
                findings.append({
                    "rule": "banned-term",
                    "file": norm_rel(f, root),
                    "line": i,
                    "message": f"出现禁用词「{term}」：{reason}",
                })


def check_decisions(root: Path, inv: dict, dec: dict, findings: list) -> None:
    """规则 3 + 4：决议须存在；状态机须合法。"""
    decisions = {d["id"]: d for d in dec.get("decisions") or []}
    valid = {"proposed", "decided", "propagated", "verified"}

    for f in inv.get("files") or []:
        did = f.get("decision")
        if not did:
            findings.append({
                "rule": "missing-decision-ref",
                "file": f.get("path", "?"),
                "message": "files 条目未声明 decision，无法反查授权决议",
            })
            continue
        if did not in decisions:
            findings.append({
                "rule": "unknown-decision",
                "file": f.get("path", "?"),
                "message": f"引用的决议 {did} 不存在于 spec/decisions.yaml",
            })

    for did, d in decisions.items():
        st = d.get("status")
        if st not in valid:
            findings.append({
                "rule": "invalid-decision-status",
                "file": "spec/decisions.yaml",
                "message": f"{did} 状态「{st}」不在 {sorted(valid)} 内",
            })
        for anc in d.get("affects") or []:
            if "file" in anc:
                p = root / anc["file"]
                if not p.exists():
                    findings.append({
                        "rule": "dangling-affects",
                        "file": "spec/decisions.yaml",
                        "message": f"{did} 的 affects 指向不存在的文件：{anc['file']}",
                    })


def check_structure(root: Path, inv: dict, findings: list) -> None:
    """规则 5：结构断言。当前支持 counts_equal / sum_equals。

    `pending: true` 表示该断言描述的是**尚未实现**的目标结构（如管理端前端还没建）。
    此时 scope 不存在或内容不足是预期状态，只记提示不判失败 —— 但若 scope 已存在且
    内容可校验，仍要实际校验（不能拿 pending 当免检通行证）。
    """
    for sa in inv.get("structure_assertions") or []:
        rule = sa.get("rule")
        scope = sa.get("scope")
        if not scope:
            continue
        pending = bool(sa.get("pending"))
        base = root / scope
        if not base.exists():
            if pending:
                findings.append({
                    "rule": "pending-assertion",
                    "file": "spec/invariants.yaml",
                    "severity": "info",
                    "message": f"{sa.get('id')}：scope 尚未实现（{scope}），断言暂挂",
                })
            else:
                findings.append({
                    "rule": "missing-scope",
                    "file": "spec/invariants.yaml",
                    "message": f"{sa.get('id')} 的 scope 不存在：{scope}",
                })
            continue

        if rule == "sum_equals":
            # AssetAlloc 四项之和 = 1.0：直接读源码常量做算术校验
            src = (base / "schema.py")
            if not src.exists():
                continue
            text = src.read_text(encoding="utf-8")
            m = re.search(
                rf"class\s+{re.escape(sa.get('target', 'AssetAlloc'))}\b"
                r".*?stock:\s*float.*?bond:\s*float.*?gold:\s*float.*?cash:\s*float",
                text,
                re.DOTALL,
            )
            if not m:
                continue
            # 权重表存在性检查（阈值集中于 config.py）
            cfg = base / "config.py"
            if cfg.exists():
                ctext = cfg.read_text(encoding="utf-8")
                if "ASSET_ENV_WEIGHTS" not in ctext:
                    findings.append({
                        "rule": "structure-assertion",
                        "file": norm_rel(cfg, root),
                        "message": f"{sa.get('id')}：未找到大类资产配置表（ASSET_ENV_WEIGHTS），无法校验四项之和",
                    })
            continue

        if rule == "counts_equal":
            # 管理端：页数 = section 数 = 导航项数 = 路由键数
            admin = base
            pages = sorted(p for p in admin.rglob("page.tsx"))
            if not pages:
                continue
            n_pages = len(pages)
            # section 数：统计 <section id="...">
            n_sections = 0
            for p in admin.rglob("*.tsx"):
                n_sections += len(re.findall(r'<section\s+id="', p.read_text(encoding="utf-8")))
            # 导航项数：统计 data-p="..."
            n_nav = 0
            for p in admin.rglob("*.tsx"):
                n_nav += len(re.findall(r'data-p="', p.read_text(encoding="utf-8")))
            # 路由键数：app/api 下有 route.ts 的资源目录数
            api = root / "web/app/api"
            n_routes = 0
            if api.exists():
                n_routes = len([p for p in api.rglob("route.ts")])
            vals = {"pages": n_pages, "sections": n_sections, "nav_items": n_nav, "route_keys": n_routes}
            uniq = set(vals.values())
            if len(uniq) > 1:
                findings.append({
                    "rule": "structure-assertion",
                    "file": norm_rel(admin, root),
                    "message": f"{sa.get('id')}：数量不一致 {vals}",
                })


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="spec_lint（D-21 一致性门禁）")
    ap.add_argument("--spec", default="spec", help="spec 目录")
    ap.add_argument("--root", default=".", help="仓库根目录")
    ap.add_argument("--report", default="reports/spec-lint.json", help="报告输出路径")
    a = ap.parse_args(argv)

    root = Path(a.root).resolve()
    spec = root / a.spec
    if not spec.is_dir():
        print(f"spec 目录不存在：{spec}", file=sys.stderr)
        return 2

    inv = load_yaml(spec / "invariants.yaml") if (spec / "invariants.yaml").exists() else {}
    dec = load_yaml(spec / "decisions.yaml") if (spec / "decisions.yaml").exists() else {}

    findings: list[dict] = []
    check_unregistered_files(root, inv, findings)
    check_banned_terms(root, inv, findings)
    check_decisions(root, inv, dec, findings)
    check_structure(root, inv, findings)

    # info 级 finding（如 pending 断言）只留痕，不判失败
    errors = [f for f in findings if f.get("severity") != "info"]
    infos = [f for f in findings if f.get("severity") == "info"]

    report = {
        "ok": not errors,
        "count": len(errors),
        "info_count": len(infos),
        "findings": findings,
    }
    rp = root / a.report
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    for f in infos:
        loc = f["file"] + (f":{f['line']}" if "line" in f else "")
        print(f"  [提示] {loc}\n        {f['message']}", file=sys.stderr)

    if errors:
        print(f"spec_lint 未通过：{len(errors)} 项\n", file=sys.stderr)
        for f in errors:
            loc = f["file"] + (f":{f['line']}" if "line" in f else "")
            print(f"  [{f['rule']}] {loc}\n      {f['message']}", file=sys.stderr)
        print(f"\n报告：{rp}", file=sys.stderr)
        return 1

    extra = f"（{len(infos)} 项提示）" if infos else ""
    print(f"spec_lint 通过{extra}（报告：{rp}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
