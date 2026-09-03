# 무인 루틴 실행 (Windows)
#
# 사람이 화면 앞에 없는 상태로 돈다. 확인이 필요한 행동은 시도하지 않는다
# (SECURITY.md §7). 조회하고 파일로 남기는 것까지만 한다.
#
#   .\scripts\run_routine.ps1 morning-brief
#
# CLI 경로
# --------
# 무인 실행은 래퍼 UI 가 아니라 CLI 를 직접 부른다. H Code Desktop 같은
# 래퍼가 CLI 를 번들로 갖고 있으면 PATH 에 없을 수 있으므로 다음 순서로
# 찾는다: $env:HMG_CLAUDE_BIN -> PATH -> 흔한 설치 위치.
#
#   $env:HMG_CLAUDE_BIN = "C:\Program Files\H Code Desktop\resources\claude.exe"
#
# 작업 스케줄러 등록 예 (평일 08:00) — 관리자 PowerShell 에서:
#   $a = New-ScheduledTaskAction -Execute "powershell.exe" `
#          -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\<워크스페이스>\scripts\run_routine.ps1 morning-brief"
#   $t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Mon,Tue,Wed,Thu,Fri -At 08:00
#   Register-ScheduledTask -TaskName "HMG-Agent-MorningBrief" -Action $a -Trigger $t
#
# 스케줄러는 사용자 PATH 를 물려받지 않을 수 있다. HMG_CLAUDE_BIN 을
# 시스템 환경 변수로 등록하거나 아래 후보 목록에 실제 경로를 추가할 것.

param(
    [Parameter(Mandatory = $true)]
    [string]$Routine
)

$ErrorActionPreference = "Continue"

$Workspace = Split-Path -Parent $PSScriptRoot
Set-Location $Workspace

$Today   = Get-Date -Format "yyyy-MM-dd"
$LogDir  = Join-Path $Workspace "logs\$Today"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "$Routine.log"

# --- CLI 찾기 -------------------------------------------------------------
$Candidates = @(
    $env:HMG_CLAUDE_BIN,
    (Get-Command claude -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
    "$env:LOCALAPPDATA\Programs\claude\claude.exe",
    "$env:APPDATA\npm\claude.cmd",
    "C:\Program Files\H Code Desktop\resources\claude.exe",
    "$env:LOCALAPPDATA\Programs\H Code Desktop\resources\claude.exe"
)

$ClaudeBin = $null
$Tried = @()
foreach ($c in $Candidates) {
    if ([string]::IsNullOrWhiteSpace($c)) { continue }
    $Tried += "  - $c"
    if (Test-Path $c) { $ClaudeBin = $c; break }
}

if (-not $ClaudeBin) {
    $msg = @"
[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Claude Code CLI 를 찾지 못했습니다.
다음 위치를 확인했습니다:
$($Tried -join "`n")

래퍼가 CLI 를 번들로 갖고 있다면 경로를 지정하십시오:
  `$env:HMG_CLAUDE_BIN = "C:\경로\claude.exe"
자세한 내용은 HARNESS.md §5 참조.
"@
    Add-Content -Path $LogFile -Value $msg -Encoding UTF8
    Write-Error $msg
    exit 1
}

Add-Content -Path $LogFile -Encoding UTF8 -Value @"
====================================================
[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 루틴 시작: /$Routine
CLI: $ClaudeBin
====================================================
"@

# --permission-mode acceptEdits: 파일 저장은 통과시키되, 발송·변경은
# guard_external_actions.py 훅이 여전히 잡는다.
& $ClaudeBin -p "/$Routine" --permission-mode acceptEdits 2>&1 |
    Out-File -FilePath $LogFile -Append -Encoding UTF8
$Status = $LASTEXITCODE

Add-Content -Path $LogFile -Encoding UTF8 -Value "`n[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 종료 코드 $Status"

if ($Status -ne 0) {
    Write-Error "루틴 /$Routine 실패 (코드 $Status). 로그: $LogFile"
}

exit $Status
