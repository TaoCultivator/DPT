<#
.SYNOPSIS
    DPT 工程临时产物清理器（默认 dry-run）。

.DESCRIPTION
    清理 E:\Works\DPT 下的临时构建产物目录：
      - .tmp        中间抽取产物 / 巨型 xlsx 原始样本 / pytest 临时目录
      - .codex_tmp  Codex 会话临时文件

    安全设计：
      1. 默认 dry-run，只打印清单与体积，不删除任何文件。
      2. 需显式 -Execute 才真正删除。
      3. -IncludeCodexTmp 需额外显式开启，避免误删仍在使用的会话缓存。
      4. 删除前先做引用自检：若源码中出现指向目标的硬编码路径，直接中止。

.PARAMETER Root
    工程根目录，默认 E:\Works\DPT。

.PARAMETER Execute
    真正执行删除。不传则只做 dry-run 盘点。

.PARAMETER IncludeCodexTmp
    一并清理 .codex_tmp。

.PARAMETER KeepPattern
    保留的文件名通配符（默认保留清理脚本自身与说明文档）。

.EXAMPLE
    # 只看清单
    .\scripts\clean_temp_artifacts.ps1

.EXAMPLE
    # 真正清理 .tmp（保留 .codex_tmp）
    .\scripts\clean_temp_artifacts.ps1 -Execute

.EXAMPLE
    # 全部清理
    .\scripts\clean_temp_artifacts.ps1 -Execute -IncludeCodexTmp
#>
[CmdletBinding()]
param(
    [string]$Root = 'E:\Works\DPT',
    [switch]$Execute,
    [switch]$IncludeCodexTmp,
    [string[]]$KeepPattern = @('clean_temp_artifacts.ps1', 'tmp_cleanup_inventory.md')
)

$ErrorActionPreference = 'Stop'
$Targets = @('.tmp')
if ($IncludeCodexTmp) { $Targets += '.codex_tmp' }

Write-Host "=== DPT 临时产物清理 ===" -ForegroundColor Cyan
Write-Host ("Root      : {0}" -f $Root)
Write-Host ("Mode      : {0}" -f $(if ($Execute) { 'EXECUTE（真实删除）' } else { 'DRY-RUN（仅盘点）' }))
Write-Host ("Targets   : {0}" -f ($Targets -join ', '))
Write-Host ''

# ---------- 1. 引用自检 ----------
Write-Host '[1/3] 源码引用自检 ...' -ForegroundColor Yellow
$codeExts = @('.py', '.ps1', '.bat', '.cmd', '.toml', '.cfg', '.ini', '.spec')
# 只扫描真实源码目录与根目录下的正规文件，避免把 .tmp_*.ps1 等临时脚本算作引用
$scanDirs = @('dpt_extractor', 'scripts', 'tests', 'docs')
$scanRoots = @()
foreach ($d in $scanDirs) {
    $p = Join-Path $Root $d
    if (Test-Path -LiteralPath $p) { $scanRoots += $p }
}
$codeFiles = @()
foreach ($r in $scanRoots) {
    $codeFiles += Get-ChildItem -LiteralPath $r -Recurse -File -ErrorAction SilentlyContinue
}
$codeFiles += Get-ChildItem -LiteralPath $Root -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike '.tmp*' }
$codeFiles = $codeFiles |
    Where-Object {
        $codeExts -contains $_.Extension -and
        $_.Name -ne 'clean_temp_artifacts.ps1' -and
        $_.FullName -notmatch '\\\.tmp\\|\\\.codex_tmp\\|\\\.git\\|__pycache__|\\\.venv\\|node_modules'
    }

$refHits = @()
foreach ($t in $Targets) {
    $needle = '\' + $t
    $refHits += $codeFiles | Select-String -SimpleMatch -Pattern $needle -ErrorAction SilentlyContinue
}

if ($refHits.Count -gt 0) {
    Write-Host ("  发现 {0} 处硬编码引用，中止清理：" -f $refHits.Count) -ForegroundColor Red
    $refHits | Select-Object -First 20 | ForEach-Object {
        Write-Host ("    {0}:{1}: {2}" -f $_.Path, $_.LineNumber, $_.Line.Trim())
    }
    Write-Host '  如确认可忽略，请先修正代码或手工删除后再运行。' -ForegroundColor Red
    exit 2
}
Write-Host ("  OK：扫描 {0} 个源码文件，未发现硬编码引用。" -f $codeFiles.Count) -ForegroundColor Green
Write-Host ''

# ---------- 2. 盘点 ----------
Write-Host '[2/3] 盘点目标目录 ...' -ForegroundColor Yellow
$allPlan = @()
foreach ($t in $Targets) {
    $path = Join-Path $Root $t
    if (-not (Test-Path -LiteralPath $path)) {
        Write-Host ("  {0,-12} 不存在，跳过" -f $t) -ForegroundColor DarkGray
        continue
    }
    $files = Get-ChildItem -LiteralPath $path -Recurse -File -ErrorAction SilentlyContinue
    $sum = ($files | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $sum) { $sum = 0 }
    Write-Host ("  {0,-12} files={1,8}  size={2,10:N2} MB" -f $t, $files.Count, ($sum / 1MB)) -ForegroundColor White

    $big = $files | Sort-Object Length -Descending | Select-Object -First 5
    foreach ($f in $big) {
        Write-Host ("      {0,10:N1} MB  {1}" -f ($f.Length / 1MB), $f.FullName.Replace($Root + '\', ''))
    }
    $allPlan += [pscustomobject]@{ Target = $t; Path = $path; Count = $files.Count; Bytes = $sum }
}
Write-Host ''

# ---------- 3. 执行 ----------
Write-Host '[3/3] 执行阶段 ...' -ForegroundColor Yellow
if (-not $Execute) {
    Write-Host '  DRY-RUN 结束，未删除任何文件。' -ForegroundColor Cyan
    Write-Host '  确认无误后加 -Execute 参数重跑。' -ForegroundColor Cyan
    exit 0
}

foreach ($item in $allPlan) {
    try {
        # ---- 安全护栏 1：跳过所有 git worktree ----
        # .tmp 下可能藏有 live worktree（例如 .tmp\blocker_diag\wt_issue8
        # 曾检出 12994 行未提交改动 + 16 个未跟踪新文件）。worktree 是活
        # 的工作副本，绝不是缓存，必须整棵跳过。
        $worktreePaths = @()
        try {
            $wtRaw = & git -C $Root worktree list --porcelain 2>$null
            foreach ($line in $wtRaw) {
                if ($line -like 'worktree *') { $worktreePaths += $line.Substring(9).Trim() }
            }
        }
        catch { Write-Host '  警告：git worktree list 失败，改用目录启发式保护' -ForegroundColor Yellow }

        Get-ChildItem -LiteralPath $item.Path -Force -ErrorAction SilentlyContinue | ForEach-Object {
            $entry = $_
            $fullPath = $entry.FullName

            # 保留名单
            foreach ($k in $KeepPattern) {
                if ($entry.Name -like $k) {
                    Write-Host ("  跳过（保留名单）：{0}" -f $entry.Name) -ForegroundColor DarkGray
                    return
                }
            }

            # 护栏 1：命中任何已登记 worktree（含其子目录）
            $isWorktree = $false
            foreach ($wt in $worktreePaths) {
                $wtNorm = $wt.Replace('/', '\').TrimEnd('\')
                if ($fullPath.Replace('/', '\').TrimEnd('\') -eq $wtNorm -or
                    $wtNorm.StartsWith($fullPath.Replace('/', '\').TrimEnd('\') + '\')) {
                    $isWorktree = $true
                    break
                }
            }
            if ($isWorktree) {
                Write-Host ("  ⚠ 跳过 live worktree：{0}" -f $entry.Name) -ForegroundColor Yellow
                return
            }

            # 护栏 2：目录内若含 .git，视为仓库副本，不递归删除
            if ($entry.PSIsContainer) {
                if (Test-Path -LiteralPath (Join-Path $fullPath '.git')) {
                    Write-Host ("  ⚠ 跳过含 .git 的目录：{0}" -f $entry.Name) -ForegroundColor Yellow
                    return
                }
                # 护栏 3：仅当目标目录【自身】含 .git（文件或目录）时才做未提交改动检查。
                # 修正原因：旧逻辑对任意子目录执行 `git -C $fullPath status --porcelain`，
                # git 会向上级目录查找并命中父仓库的 .git，把父仓库的全部改动（曾达 173 处）
                # 误判成该子目录的未提交改动，导致所有子目录被跳过、清理形同虚设。
                # 现在：自身没有 .git 就不是独立仓库/worktree，跳过检查直接删除。
                if (Test-Path -LiteralPath (Join-Path $fullPath '.git')) {
                    $dirtyCheck = & git -C $fullPath status --porcelain 2>$null
                    if ($LASTEXITCODE -eq 0 -and $dirtyCheck) {
                        Write-Host ("  ⚠ 跳过有未提交改动的 git 目录：{0}（{1} 处改动）" -f $entry.Name, ($dirtyCheck | Measure-Object).Count) -ForegroundColor Yellow
                        return
                    }
                }
            }

            try {
                Remove-Item -LiteralPath $fullPath -Recurse -Force -ErrorAction Stop
            }
            catch {
                Write-Host ("  删除失败 {0}：{1}" -f $entry.Name, $_.Exception.Message) -ForegroundColor Red
            }
        }
        Write-Host ("  已清理 {0}（{1:N2} MB）" -f $item.Target, ($item.Bytes / 1MB)) -ForegroundColor Green
    }
    catch {
        Write-Host ("  清理 {0} 时出错：{1}" -f $item.Target, $_.Exception.Message) -ForegroundColor Red
    }
}

Write-Host ''
Write-Host '完成。' -ForegroundColor Green
