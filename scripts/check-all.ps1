<#
.SYNOPSIS
    本地全量自检（提交前 / 推送前跑一次）。

.DESCRIPTION
    串行执行仓库的全部本地门禁，任一失败即中止并返回非零：
      1. spec_lint   —— 文档与决议一致性（D-21）
      2. ruff        —— Python 代码风格
      3. pytest      —— 单元测试 + 覆盖率门槛（≥80%）
      4. tsc         —— 前端类型检查
      5. eslint      —— 前端 lint
      6. vitest      —— 前端单测
      7. next build  —— 前端构建

    CI 跑在同一批门禁上；本脚本用于本地提前发现问题，避免推上去才发现红。

    ⚠️ 2026-11-18：早期生成代码已清除，仓库为治理空壳。当前仅第 1 项 spec_lint 可用；
       第 2~7 项依赖 cli/ 与 web/ 目录，本地代码重建前会失败，属预期。重建后本脚本自动恢复。

.EXAMPLE
    .\scripts\check-all.ps1
    .\scripts\check-all.ps1 -SkipBuild    # 跳过 next build（较慢）
#>
[CmdletBinding()]
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$failed = @()

function Invoke-Step {
    param(
        [string]$Name,
        [string]$Dir,
        [scriptblock]$Command
    )
    Write-Host "`n=== $Name ===" -ForegroundColor Cyan
    Push-Location $Dir
    & $Command
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) {
        Write-Host "❌ $Name 失败（退出码 $code）" -ForegroundColor Red
        $script:failed += $Name
    } else {
        Write-Host "✅ $Name 通过" -ForegroundColor Green
    }
}

Invoke-Step -Name 'spec_lint' -Dir $root -Command {
    python "$root\scripts\spec_lint.py" --spec "$root\spec" --root $root
}

Invoke-Step -Name 'ruff（Python）' -Dir "$root\cli" -Command {
    ruff check .
}

Invoke-Step -Name 'pytest（Python）' -Dir "$root\cli" -Command {
    pytest -q --cov=dq --cov-report=term --cov-fail-under=80
}

Invoke-Step -Name 'tsc（前端类型）' -Dir "$root\web" -Command {
    npm run typecheck
}

Invoke-Step -Name 'eslint（前端）' -Dir "$root\web" -Command {
    npm run lint
}

Invoke-Step -Name 'vitest（前端单测）' -Dir "$root\web" -Command {
    npm test
}

if (-not $SkipBuild) {
    Invoke-Step -Name 'next build（前端构建）' -Dir "$root\web" -Command {
        npm run build
    }
}

Write-Host ""
if ($failed.Count -gt 0) {
    Write-Host "以下门禁未通过：$($failed -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "全部门禁通过。" -ForegroundColor Green
exit 0
