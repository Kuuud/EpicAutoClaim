$TaskName = "Epic Auto Claim"

Write-Host "正在删除任务..."

schtasks /Delete /TN "$TaskName" /F

Write-Host ""
Write-Host "Epic Auto Claim 定时任务已删除。"

Read-Host "按 Enter 退出"