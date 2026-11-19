#!/usr/bin/env bash
# 恢复 git 推送凭据（幂等）
#
# 背景：SSH 私钥托管在项目资产（网盘）里，密钥本身是沙箱易失载体。
#       沙箱重建后私钥丢失，此脚本从网盘直链取回并重新安装。
#
# 用法：
#   bash scripts/restore-git-credential.sh <download_url>
#   bash scripts/restore-git-credential.sh --from-file <path>
#   bash scripts/restore-git-credential.sh --check          # 只体检，不改动
#
# 直链获取方式（由 agent 调用 MCP 签发，勿手写）：
#   mcp__netdrive__tdrive.file_download  { file_id: "<资产文件 id>" }
#   → 返回 download_url 原样传给本脚本
set -euo pipefail

export PATH="$PATH:/usr/bin:/bin"

# 托管的是仓库级 Deploy Key；可用 DQ_SSH_KEY 覆盖
KEY_NAME="${DQ_SSH_KEY:-id_ed25519_dq_deploy}"
KEY_PATH="${HOME}/.ssh/${KEY_NAME}"
CONFIG_PATH="${HOME}/.ssh/config"
REMOTE_REPO="zhonghongmin/deepquantor"

ok()   { echo "✅ $*"; }
fail() { echo "❌ $*" >&2; exit 1; }

# ── 0. 体检模式 ────────────────────────────────────────────────
check_only=0
from_file=""
url=""
for a in "$@"; do
  case "$a" in
    --check)     check_only=1 ;;
    --from-file) shift; from_file="${1:-}" ;;
    http*)       url="$a" ;;
  esac
  shift || true
done

ssh_probe() {
  # 必须用 -F /dev/null 隔离 ~/.ssh/config：
  # 命令行的 -i 是「追加」而非「覆盖」，config 里残留的 IdentityFile 仍会被尝试，
  # 导致目标 key 认证失败时悄悄回退到另一把 key（实测踩过）。
  # -F /dev/null 后 User/HostName 需手动指定。
  ssh -F /dev/null -T -i "$KEY_PATH" -o IdentitiesOnly=yes -o BatchMode=yes \
      -o User=git -o HostName=github.com -o StrictHostKeyChecking=accept-new \
      -o ServerAliveInterval=30 git@github.com 2>&1 || true
}

auth_ok() {
  grep -q "successfully authenticated" <<<"$(ssh_probe)"
}

if [ "$check_only" = "1" ]; then
  echo "=== 凭据体检 ==="
  echo "目标私钥  : ${KEY_PATH}"
  echo "私钥存在  : $([ -f "$KEY_PATH" ] && echo yes || echo no)"
  echo "配置存在  : $([ -f "$CONFIG_PATH" ] && echo yes || echo no)"
  if auth_ok; then
    out="$(ssh_probe)"
    echo "认证状态  : 可用"
    case "$out" in
      *"$REMOTE_REPO"*) echo "密钥类型  : 仓库级 Deploy Key（权限仅 ${REMOTE_REPO}）✓" ;;
      *)                echo "密钥类型  : 账号级 SSH Key（权限=账号全部仓库，⚠ 建议改用 Deploy Key）" ;;
    esac
    exit 0
  else
    echo "认证状态  : 不可用 → 需从项目资产恢复"
    exit 1
  fi
fi

# ── 1. 已可用则直接退出（幂等）────────────────────────────────
if auth_ok; then
  ok "凭据已可用，无需恢复"
  exit 0
fi

# ── 2. 取回私钥 ────────────────────────────────────────────────
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

if [ -n "$from_file" ]; then
  [ -f "$from_file" ] || fail "文件不存在: $from_file"
  cp "$from_file" "$tmp"
elif [ -n "$url" ]; then
  curl -sSL -o "$tmp" "$url" || fail "下载失败"
else
  fail "未提供 download_url 或 --from-file；用 --check 可单独体检"
fi

# 下载物可能是 XML 错误体（AK 失效），必须先验内容再安装
if head -c 400 "$tmp" | grep -qE "<Error>|InvalidAccessKeyId|SignatureDoesNotMatch"; then
  fail "下载到的是错误体而非私钥（临时 AK 失效）——重新签发直链后重试"
fi
if ! head -1 "$tmp" | grep -q "OPENSSH PRIVATE KEY"; then
  fail "内容不是 OpenSSH 私钥（前 40 字节：$(head -c 40 "$tmp" | tr -d '\0')）"
fi

# ── 3. 安装 ────────────────────────────────────────────────────
mkdir -p "$(dirname "$KEY_PATH")"
chmod 700 "$(dirname "$KEY_PATH")"
install -m 600 "$tmp" "$KEY_PATH"

# 备份原 config，再全量覆盖 —— 覆盖是必要的：
# config 中若残留别的 IdentityFile，SSH 会先试它们再试目标 key，
# 导致「托管的是 deploy key，实际推的却是账号级 key」。
[ -f "$CONFIG_PATH" ] && cp "$CONFIG_PATH" "${CONFIG_PATH}.bak" || true

cat > "$CONFIG_PATH" <<EOF
Host github.com
    HostName github.com
    User git
    IdentityFile ${KEY_PATH}
    IdentitiesOnly yes
    StrictHostKeyChecking accept-new
    ServerAliveInterval 30
EOF
chmod 600 "$CONFIG_PATH"

extra=$(grep -c "IdentityFile" "$CONFIG_PATH")
[ "$extra" = "1" ] || fail "config 中 IdentityFile 条目数为 $extra，应为 1"

# ── 4. 验证 ────────────────────────────────────────────────────
if auth_ok; then
  out="$(ssh_probe)"
  ok "凭据已恢复并验证通过"
  echo "   ${out}"
  case "$out" in
    *"$REMOTE_REPO"*) echo "   类型：仓库级 Deploy Key（权限仅 ${REMOTE_REPO}）" ;;
    *)                echo "   类型：账号级 SSH Key（权限为该账号全部仓库，建议换成 Deploy Key）" ;;
  esac
else
  fail "安装完成但认证仍失败 —— 公钥可能未在 GitHub 注册，或已被删除"
fi
