<#
.SYNOPSIS
    deepquantor 本地仓库初始化（Windows PowerShell 5.1+ / PowerShell 7 均可）。

.DESCRIPTION
    在 D:\develop\deepquantor 初始化 git 仓库并做首次提交。幂等：重复执行安全。

    做四件事：
      1. 校验前置（git 是否安装、目录是否为空、是否有未提交改动）
      2. git init + 配置身份（仅当全局未配置时才写入本地仓库，避免覆盖用户全局设置）
      3. 建立 main 分支 + 拉取远端首次推送
      4. 打印下一步提示

    ⚠️ 不会做的事：不改全局 git 配置、不装依赖、不删任何文件、不提交 .env。

.PARAMETER Remote
    远端仓库地址。留空则只做本地初始化（稍后手动 add remote）。

.PARAMETER SkipInitialCommit
    跳过首次提交（用于先拉取远端已有历史的情形）。

.EXAMPLE
    .\init-repo.ps1
    .\init-repo.ps1 -Remote https://git.woa.com/<group>/deepquantor.git
#>
[CmdletBinding()]
param(
    [string]$Remote = '',
    [switch]$SkipInitialCommit
)

$ErrorActionPreference = 'Stop'
$RepoRoot = 'D:\develop\deepquantor'

function Write-Step  { param($m) Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok    { param($m) Write-Host "  ✓ $m" -ForegroundColor Green }
function Write-Warn  { param($m) Write-Host "  ! $m" -ForegroundColor Yellow }
function Write-Err   { param($m) Write-Host "  ✗ $m" -ForegroundColor Red }

# ── 1. 前置校验 ──────────────────────────────────────────────────────
Write-Step "1/4 前置校验"

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Err "未找到 git。请先安装：https://git-scm.com/download/win （选 Git for Windows，含 Git Bash）"
    Write-Err "装完后重新打开 PowerShell 再跑本脚本。"
    exit 1
}
Write-Ok "git 已安装：$((git --version))"

if (-not (Test-Path $RepoRoot)) {
    Write-Err "目标目录不存在：$RepoRoot"
    Write-Err "请先建目录，或修改脚本顶部的 `$RepoRoot 变量。"
    exit 1
}
Write-Ok "目标目录存在：$RepoRoot"

# 已有 .git → 视为已初始化，提示后退出（幂等）
if (Test-Path (Join-Path $RepoRoot '.git')) {
    Write-Warn "该目录已是 git 仓库，跳过初始化。"
    Write-Host ""
    Write-Host "常用命令（在 $RepoRoot 下执行）：" -ForegroundColor Cyan
    Write-Host "  git status              # 查看状态"
    Write-Host "  git add -A; git commit -m 'msg'"
    Write-Host "  git push                # 推送 main"
    Write-Host "  git pull --rebase       # 拉取远端"
    exit 0
}

Push-Location $RepoRoot

# 检查是否有未纳入版本管理的既有文件（只提示，不阻断）
$existing = @(Get-ChildItem -Force | Where-Object { $_.Name -notin @('.git') })
if ($existing.Count -gt 0) {
    Write-Warn "目录非空，已有 $($existing.Count) 项（含文件与子目录）。首次提交会包含其中未被 .gitignore 排除的内容。"
    Write-Host "    请确认 .gitignore 已就位（尤其 .env 与凭证文件）。" -ForegroundColor Yellow
}

# ── 2. git init ──────────────────────────────────────────────────────
Write-Step "2/4 初始化仓库"

git init -b main 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    # 旧版 git 不支持 -b
    git init 2>&1 | Out-Null
    git symbolic-ref HEAD refs/heads/main
}
Write-Ok "已初始化仓库，默认分支 main"

# 身份：全局已配就不动；未配则只在本地仓库写，避免污染全局
$globalName  = (git config --global user.name)
$globalEmail = (git config --global user.email)
if ($globalName -and $globalEmail) {
    Write-Ok "提交身份沿用全局配置：$globalName <$globalEmail>"
} else {
    Write-Warn "全局 git 身份未配置完整，请在下方输入（仅写入本仓库，不改全局配置）。"
    $name  = Read-Host "  user.name  [$globalName]"
    $email = Read-Host "  user.email [$globalEmail]"
    if ($name)  { git config user.name $name }
    if ($email) { git config user.email $email }
    if ($name -and $email) { Write-Ok "本仓库身份已设置：$name <$email>" }
    else { Write-Warn "未设置身份，后续提交前请先补：git config user.name / user.email" }
}

# ── 3. 远端与首次提交 ────────────────────────────────────────────────
Write-Step "3/4 远端与首次提交"

if ($Remote -ne '') {
    $existingRemote = (git remote 2>$null)
    if ($existingRemote -contains 'origin') {
        Write-Ok "origin 已存在：$((git remote get-url origin))"
    } else {
        git remote add origin $Remote
        Write-Ok "已设置 origin：$Remote"
    }
} else {
    Write-Warn "未指定 -Remote，跳过远端设置（本地仓库照常可用）。"
}

if (-not $SkipInitialCommit) {
    git add -A
    if ($LASTEXITCODE -ne 0) { Write-Err "git add 失败"; Pop-Location; exit 1 }

    $staged = @(git diff --cached --name-only)
    if ($staged.Count -eq 0) {
        Write-Warn "暂存区为空（可能全部被 .gitignore 排除），跳过首次提交。"
    } else {
        Write-Ok "已暂存 $($staged.Count) 个文件"
        # 安全检查：.env 若被暂存则中止（凭证边界 NFR-07）
        $envStaged = @($staged | Where-Object { $_ -match '(^|/)\.env($|\.)' -and $_ -notmatch '\.example$' })
        if ($envStaged.Count -gt 0) {
            Write-Err "检测到 .env 被暂存：$($envStaged -join ', ')"
            Write-Err "凭证不入版本库（NFR-07）。已中止提交，请先修 .gitignore 并 git reset。"
            Pop-Location
            exit 1
        }
        Write-Ok "凭证安全检查通过（无 .env 入库）"

        git commit -m "chore: 初始化仓库骨架

- Python CLI（dq 包）+ Node Web 双层目录结构
- spec/ 单一事实源、deploy/ 部署侧、migrations/ 迁移目录
- CI 门禁：spec_lint + pytest + Vitest + 迁移回滚配对检查
- .env 不入库（NFR-07）" 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) { Write-Err "首次提交失败"; Pop-Location; exit 1 }
        Write-Ok "首次提交完成"

        if ($Remote -ne '') {
            git push -u origin main
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "已推送到 origin/main"
            } else {
                Write-Warn "推送失败（远端仓库可能尚不存在或权限不足）。"
                Write-Host "    先在远端平台创建空仓库，再重跑：git push -u origin main" -ForegroundColor Yellow
            }
        }
    }
}

Pop-Location

# ── 4. 下一步 ────────────────────────────────────────────────────────
Write-Step "4/4 下一步"
Write-Host @"
  1) 装依赖（内网 PyPI 慢，务必用清华源）：
       cd $RepoRoot\cli
       uv venv --python 3.11
       uv pip install -e ".[dev]" --index-url https://pypi.tuna.tsinghua.edu.cn/simple
       uv pip compile pyproject.toml -o requirements.lock --index-url https://pypi.tuna.tsinghua.edu.cn/simple

  2) 装 Web 依赖：
       cd $RepoRoot\web
       npm install

  3) 落配置：
       Copy-Item ..\deploy\env\.env.example ..\deploy\env\.env   # 然后填实际值

  4) 跑测试确认基线：
       cd $RepoRoot\cli ; pytest -v
       cd $RepoRoot\web ; npm test

"@ -ForegroundColor Gray
Write-Host "仓库已就绪。" -ForegroundColor Green
