
# Epic Auto Claim GUI

双账号 Epic 自动领取工具：
- Edge 与 Chrome 使用完全独立的 Playwright Profile
- GUI 中可分别启用/禁用 Edge、Chrome
- 首次运行分别手动登录 Epic
- 不保存 Epic 用户名/密码
- 可手动“立即领取”
- 可设置每周自动任务参数
- 日志、异常截图独立保存

## 安装

```powershell
cd EpicAutoClaim
py -m pip install -r requirements.txt
py -m playwright install chromium
python main.py
```

第一次运行：
1. 保持“启用 Edge”和“启用 Chrome”。
2. 点击“立即领取”。
3. Edge 首次打开后登录 Epic 账号 A。
4. Chrome 首次打开后登录 Epic 账号 B。
5. 登录状态会保存在 profiles/edge 和 profiles/chrome。

## 自动任务

运行：

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\install.ps1
```

默认每周四 18:00 运行。

## 注意

Epic 页面 DOM 会变化，因此自动领取部分使用多个候选选择器。CAPTCHA、2FA 等安全验证需要人工完成，程序不绕过这些验证。
