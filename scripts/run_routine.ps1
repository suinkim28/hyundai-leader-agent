# 무인 루틴 실행 (Windows)
#
# 사람이 화면 앞에 없는 상태로 돈다. 확인이 필요한 행동은 시도하지 않는다
# (SECURITY.md §7). 조회하고 파일로 남기는 것까지만 한다.
#
#   .\scripts\run_routine.ps1 morning-brief
#
# CLI 경로
# --------
# 무인 실행은 VS Code 가 아니라 Claude Code CLI 를 직접 부른다. CLI 는 보통
# npm 전역 설치(%APPDATA%\npm\claude.cmd)라 사용자 PATH 에 있지만, 작업
# 스케줄러는 사용자 PATH 를 물려받지 않을 수 있으므로 다음 순서로 찾는다:
# $env:HMG_CLAUDE_BIN -> PATH -> 흔한 설치 위치.
#
#   $env:HMG_CLAUDE_BIN = "$env:APPDATA\npm\claude.cmd"
#
# 작업 스케줄러 등록 예 (평일 08:00): 관리자 PowerShell 에서:
#   $a = New-ScheduledTaskAction -Execute "powershell.exe" `
#          -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\<워크스페이스>\scripts\run_routine.ps1 morning-brief"
#   $t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Mon,Tue,Wed,Thu,Fri -At 08:00
#   Register-ScheduledTask -TaskName "HMG-Agent-MorningBrief" -Action $a -Trigger $t
#
# 스케줄러는 사용자 PATH 를 물려받지 않을 수 있다. HMG_CLAUDE_BIN 을
# 시스템 환경 변수로 등록하거나 아래 후보 목록에 실제 경로를 추가할 것.
#
# 인코딩 주의
# -----------
# 이 파일은 UTF-8 (BOM 포함) 으로 저장돼 있다. **BOM 을 지우지 말 것.**
# Windows PowerShell 5.1(이 스크립트를 여는 기본 powershell.exe)은 BOM 이
# 없는 .ps1 파일을 시스템 코드페이지(한국어 Windows는 cp949)로 읽는다.
# 그러면 이 파일 안의 한글 문자열이 실행 시점에 이미 깨진 채로 해석된다
# (예: "루틴 시작" 이 로그에 "猷⑦떞 ?쒖옉" 처럼 남았던 사고, 2026-09-09).
# PowerShell 7+(pwsh.exe)은 이 문제가 없지만, 배포 대상이 둘 다일 수 있어
# 가장 안전한 값인 BOM 있는 UTF-8 로 통일한다.
#
# 아래 Console/OutputEncoding 설정은 또 다른 증상을 잡는다: Windows
# PowerShell 5.1 은 파이프(`| Out-File`)로 받는 네이티브 실행파일의 출력을
# 콘솔 코드페이지로 잘못 해석해, Claude Code CLI 가 실제로 UTF-8 로 출력한
# 한글도 로그에 깨져서 남는다. 이 두 줄이 없으면 스크립트 자체는 깨끗해도
# `& $ClaudeBin` 의 출력은 여전히 깨진다.

param(
    [Parameter(Mandatory = $true)]
    [string]$Routine
)

$OutputEncoding = [System.Console]::OutputEncoding = [System.Text.Encoding]::UTF8
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
    "$env:APPDATA\npm\claude.cmd",
    "$env:LOCALAPPDATA\Programs\claude\claude.exe"
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

Claude Code CLI 설치 경로를 지정하십시오:
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

# --permission-mode acceptEdits: 파일 저장은 통과시키되, 발송, 변경은
# guard_external_actions.py 훅이 여전히 잡는다.
& $ClaudeBin -p "/$Routine" --permission-mode acceptEdits 2>&1 |
    Out-File -FilePath $LogFile -Append -Encoding UTF8
$Status = $LASTEXITCODE

Add-Content -Path $LogFile -Encoding UTF8 -Value "`n[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 종료 코드 $Status"

if ($Status -ne 0) {
    Write-Error "루틴 /$Routine 실패 (코드 $Status). 로그: $LogFile"
}

exit $Status
