"""DL-02 凭证加载：环境变量优先 → .env 兜底；AMAZINGDATA_* 桥接为 AD_*。

验收（需求文档 DL-02）：
- 环境变量全缺、.env 含 4 个键 → 全部加载且键名完成桥接；
- 两处都缺 → 抛 CredentialsError 列出缺失键名，进程不崩溃、不吞异常。
"""
from __future__ import annotations

import os
from pathlib import Path

BRIDGE_PREFIX_SRC = "AMAZINGDATA_"
BRIDGE_PREFIX_DST = "AD_"

# 首期必需凭证 4 键（银河星耀数智 + 本地 PostgreSQL）
REQUIRED_KEYS: tuple[str, ...] = ("AD_HOST", "AD_PORT", "AD_USER", "AD_TOKEN")


class CredentialsError(RuntimeError):
    """凭证缺失/非法。必须带缺失键清单，禁止吞异常。"""


def _parse_dotenv(path: Path) -> dict[str, str]:
    """最小 .env 解析：KEY=VALUE 行，# 注释，容忍引号与空白。"""
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip("'\"")
        if k:
            out[k] = v
    return out


def _bridge(key: str) -> str:
    """AMAZINGDATA_X → AD_X；其余原样。"""
    if key.startswith(BRIDGE_PREFIX_SRC):
        return BRIDGE_PREFIX_DST + key[len(BRIDGE_PREFIX_SRC):]
    return key


def load_credentials(
    env: dict[str, str] | None = None,
    dotenv_path: str | Path = ".env",
    required: tuple[str, ...] = REQUIRED_KEYS,
) -> dict[str, str]:
    """加载凭证：环境变量优先，.env 兜底；AMAZINGDATA_* 统一桥接为 AD_*。

    返回仅含 required 键的字典；任一缺失即抛 CredentialsError（列缺失键名）。
    """
    env = dict(os.environ if env is None else env)
    dotenv = _parse_dotenv(Path(dotenv_path))

    # 先做桥接视图：AD_X 可由 AD_X 或 AMAZINGDATA_X 供给，环境变量优先于 .env
    merged: dict[str, str] = {}
    for src in (*dotenv.items(), *env.items()):  # env 后写覆盖 .env
        merged[_bridge(src[0])] = src[1]

    missing = [k for k in required if not merged.get(k)]
    if missing:
        raise CredentialsError(f"凭证缺失，请配置环境变量或 .env：{', '.join(missing)}")

    return {k: merged[k] for k in required}
