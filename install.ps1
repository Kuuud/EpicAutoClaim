
$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = (Get-Command python).Source
$TaskName = "Epic Auto Claim"
$Script = Join-Path $ProjectDir "main.py"

Write-Host "安装依赖..."
& $Python -m pip install -r (Join-Path $ProjectDir "requirements.txt")
& $Python -m playwright install chromium

Write-Host "创建每周任务..."
schtasks /Delete /TN "$TaskName" /F 2>$null
$Command = "`"$Python`" `"$Script`""
schtasks /Create /TN "$TaskName" /TR $Command /SC WEEKLY /D THU /ST 18:00 /F

Write-Host ""
Write-Host "安装完成：每周四 18:00 自动运行。"
Read-Host "按 Enter 退出"
