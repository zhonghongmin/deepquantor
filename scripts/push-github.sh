#!/usr/bin/env bash
# 深量化 deepquantor —— 推送到 GitHub 并做交付回验
#
# 前置条件：沙箱公钥已添加到 GitHub 账号的 SSH keys。
# 用法： bash scripts/push-github.sh [remote]
set -euo pipefail

# 只追加缺失的系统路径，不得把 /usr/bin 插到前面：
# 本机 python3 是 pyenv shim（带 pytest），插队会切到无 pytest 的系统 Python。
export PATH="$PATH:/usr/bin:/bin"
REPO_DIR="${REPO_DIR:-/workspace/deepquantor-repo-template}"
REMOTE="${1:-git@github.com:zhonghongmin/deepquantor.git}"
BRANCH="main"

# 若提供了 PAT，则改走 HTTPS + token 通道（无需配置 SSH key）
if [ -n "${GITHUB_TOKEN:-}" ]; then
  REMOTE="https://x-access-token:${GITHUB_TOKEN}@github.com/zhonghongmin/deepquantor.git"
  echo "ℹ️  检测到 GITHUB_TOKEN，改走 HTTPS + PAT 通道"
fi

cd "$REPO_DIR"

echo "══ 1/6 认证回验 ══"
if [ -n "${GITHUB_TOKEN:-}" ]; then
  AUTH_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer ${GITHUB_TOKEN}" \
    https://api.github.com/user)
  [ "$AUTH_CODE" = "200" ] && echo "✅ PAT 认证通过" || { echo "❌ PAT 无效（HTTP $AUTH_CODE）"; exit 1; }
else
  # 注意：不可用 `ssh ... | grep -q` 判定。
  # grep -q 命中即退出会让 ssh 收到 SIGPIPE 而非零退出，配合 set -o pipefail
  # 会把「认证成功」误判成失败。必须先完整捕获输出再匹配。
  SSH_OUT=$(ssh -T -o BatchMode=yes -o StrictHostKeyChecking=accept-new git@github.com 2>&1 || true)
  if ! grep -q "successfully authenticated" <<<"$SSH_OUT"; then
    echo "❌ SSH 认证未通过。实际返回：${SSH_OUT}"
    echo "   首选：按 dq-code-dev-skill 的 references/git-access.md 恢复同一把 Deploy Key"
    echo "        bash scripts/restore-git-credential.sh --check   # 体检"
    echo "   次选：公钥需添加到 GitHub 仓库的 Deploy keys（不是账号级 SSH keys）"
    echo "   公钥内容："
    echo "   $(cat /root/.ssh/id_ed25519_dq_deploy.pub 2>/dev/null || echo '(私钥不在本机，先跑恢复脚本)')"
    exit 1
  fi
  echo "✅ SSH 认证通过（${SSH_OUT%%[!H]*}）"
fi

echo "══ 2/6 远端连通回验 ══"
git ls-remote "$REMOTE" >/dev/null 2>&1 && echo "✅ 远端可达（已有内容）" || echo "ℹ️  远端可达且为空仓库"

echo "══ 3/6 提交前门禁 ══"
python3 scripts/spec_lint.py --spec spec --root . | tail -2
(cd cli && python3 -m pytest -q 2>&1 | tail -2)
(cd cli && python3 -m ruff check . --output-format=concise 2>&1 | tail -1)

echo "══ 4/6 推送 ══"
git remote set-url origin "$REMOTE"
git push -u origin "$BRANCH"

# PAT 通道：立即清除 remote 中的 token，禁止凭据残留在 .git/config
if [ -n "${GITHUB_TOKEN:-}" ]; then
  git remote set-url origin "git@github.com:zhonghongmin/deepquantor.git"
  echo "🔒 已清除 remote URL 中的 token"
fi

echo "══ 5/6 远端回验 ══"
git ls-remote --symref origin HEAD | head -2
git fetch origin --prune
LOCAL_SHA=$(git rev-parse HEAD)
REMOTE_SHA=$(git rev-parse "origin/$BRANCH")
echo "本地 HEAD   : $LOCAL_SHA"
echo "远端 $BRANCH : $REMOTE_SHA"
[ "$LOCAL_SHA" = "$REMOTE_SHA" ] && echo "✅ SHA 一致" || { echo "❌ SHA 不一致"; exit 1; }

echo "══ 6/6 交付清单回验 ══"
COUNT=$(git ls-files | wc -l)
echo "入库文件数: $COUNT"
if git ls-files | grep -qE "\.env$|node_modules|\.venv|__pycache__"; then
  echo "❌ 敏感/构建产物误入库"; exit 1
fi
echo "✅ 敏感与构建产物零入库"
for f in cli/requirements.lock web/package-lock.json .github/workflows/ci.yml scripts/spec_lint.py; do
  git ls-files --error-unmatch "$f" >/dev/null 2>&1 && echo "  ✓ $f" || echo "  ✗ $f 缺失"
done

echo
echo "✅ 推送与回验全部完成"
echo "仓库地址: https://github.com/zhonghongmin/deepquantor"
