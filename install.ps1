$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$Python = (Get-Command python).Source

$TaskName = "Epic Auto Claim"

$RunScript = Join-Path $ProjectDir "main.py"

Write-Host "=========================================="
Write-Host " Epic Auto Claim - 安装 Windows 定时任务"
Write-Host "=========================================="
Write-Host ""

Write-Host "Python:"
Write-Host $Python

Write-Host ""
Write-Host "项目目录:"
Write-Host $ProjectDir

Write-Host ""

# 删除旧任务
schtasks /Delete /TN "$TaskName" /F 2>$null

# 每周四下午 17:00 执行
#
# Epic 免费游戏一般在周四更新。
#
$Command = "`"$Python`" `"$RunScript`""

schtasks /Create `
    /TN "$TaskName" `
    /TR $Command `
    /SC WEEKLY `
    /D THU `
    /ST 17:00 `
    /F

Write-Host ""
Write-Host "=========================================="
Write-Host "安装完成"
Write-Host "=========================================="
Write-Host ""

schtasks /Query /TN "$TaskName"

Write-Host ""
Read-Host "按 Enter 退出"