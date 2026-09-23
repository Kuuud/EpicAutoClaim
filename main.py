
import json, logging, os, re, sys, time, threading, traceback
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
PROFILE_DIR = BASE_DIR / "profiles"
LOG_DIR = BASE_DIR / "logs"
SCREENSHOT_DIR = BASE_DIR / "screenshots"
for p in (PROFILE_DIR, LOG_DIR, SCREENSHOT_DIR):
    p.mkdir(parents=True, exist_ok=True)

def load_config():
    if not CONFIG_FILE.exists():
        cfg = {
            "headless": False,
            "accounts": [
                {"name":"Edge账号","browser":"edge","enabled":True},
                {"name":"Chrome账号","browser":"chrome","enabled":True}
            ],
            "schedule":{"enabled":True,"day":"THU","time":"18:00"},
            "claim":{"timeout":30000,"retry":3,"wait_after_click":2500}
        }
        CONFIG_FILE.write_text(json.dumps(cfg,ensure_ascii=False,indent=4),encoding="utf-8")
        return cfg
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))

CONFIG = load_config()

class GuiLogHandler(logging.Handler):
    def __init__(self, app):
        super().__init__()
        self.app = app
    def emit(self, record):
        msg = self.format(record)
        self.app.after(0, self.app.append_log, msg)

logger = logging.getLogger("EpicAutoClaim")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(LOG_DIR/f"{datetime.now():%Y-%m-%d}.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)

EPIC_FREE_GAMES = "https://store.epicgames.com/en-US/free-games"
TIMEOUT = 30000

def browser_executable(browser):
    if browser == "edge":
        candidates = [
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%PROGRAMFILES%\Microsoft\Edge\Application\msedge.exe"),
        ]
    else:
        candidates = [
            os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        ]
    for p in candidates:
        if p and Path(p).exists():
            return p
    return None

def screenshot(page, name, suffix):
    safe = re.sub(r'[\\/:*?"<>| ]+', "_", name)
    path = SCREENSHOT_DIR/f"{datetime.now():%Y%m%d_%H%M%S}_{safe}_{suffix}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        logger.info("[%s] 截图：%s", name, path)
    except Exception:
        pass

def body_text(page):
    try:
        return page.locator("body").inner_text(timeout=5000).lower()
    except Exception:
        return ""

def verification_needed(page):
    text = body_text(page)
    return any(x in text for x in [
        "captcha", "verify you are human", "安全验证", "验证码",
        "two-factor", "two factor", "二步验证"
    ])

def owned(page):
    text = body_text(page)
    return any(x in text for x in [
        "in library", "owned", "已在库中", "已拥有", "已领取"
    ])

def click_candidates(page, candidates):
    for selector in candidates:
        try:
            loc = page.locator(selector)
            for i in range(min(loc.count(), 10)):
                item = loc.nth(i)
                if item.is_visible() and item.is_enabled():
                    item.scroll_into_view_if_needed()
                    item.click(timeout=5000)
                    return True
        except Exception:
            continue
    return False

def ensure_login(page, account_name):
    page.goto("https://store.epicgames.com/", wait_until="domcontentloaded", timeout=TIMEOUT)
    time.sleep(3)
    url = page.url.lower()
    text = body_text(page)
    if "login" in url or "signin" in url or "sign in" in text:
        logger.warning("[%s] 需要登录，请在浏览器中完成登录。", account_name)
        messagebox.showinfo(
            "需要登录",
            f"{account_name} 尚未登录。\n\n请在弹出的浏览器中完成 Epic 登录、验证码或 2FA，然后点击确定继续。"
        )
        deadline = time.time() + 300
        while time.time() < deadline:
            url = page.url.lower()
            if "login" not in url and "signin" not in url:
                time.sleep(3)
                return True
            time.sleep(2)
        return False
    return True

def claim_account(account):
    name, browser = account["name"], account["browser"]
    exe = browser_executable(browser)
    if not exe:
        raise RuntimeError(f"未找到 {browser} 浏览器。")

    profile = PROFILE_DIR/browser
    profile.mkdir(parents=True, exist_ok=True)
    logger.info("========== 开始：%s (%s) ==========", name, browser)

    with sync_playwright() as pw:
        context = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            executable_path=exe,
            headless=CONFIG.get("headless", False),
            viewport={"width":1440,"height":900},
            locale="zh-CN",
            args=["--disable-blink-features=AutomationControlled"]
        )
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(TIMEOUT)

            if not ensure_login(page, name):
                raise RuntimeError("登录超时")

            page.goto(EPIC_FREE_GAMES, wait_until="domcontentloaded", timeout=TIMEOUT)
            time.sleep(4)

            if verification_needed(page):
                screenshot(page, name, "verification")
                messagebox.showwarning(
                    "需要人工验证",
                    f"{name} 检测到 CAPTCHA/安全验证。\n请完成验证后点击确定。"
                )

            links = []
            anchors = page.locator("a[href]")
            for i in range(min(anchors.count(), 500)):
                try:
                    href = anchors.nth(i).get_attribute("href")
                    if href and ("/p/" in href.lower() or "/game/" in href.lower()):
                        if href.startswith("/"):
                            href = "https://store.epicgames.com" + href
                        if href not in links:
                            links.append(href)
                except Exception:
                    pass

            if not links:
                screenshot(page, name, "no_games")
                raise RuntimeError("没有找到候选游戏链接")

            success_count = 0
            for link in links[:6]:
                try:
                    page.goto(link, wait_until="domcontentloaded", timeout=TIMEOUT)
                    time.sleep(2)
                    if owned(page):
                        logger.info("[%s] 已拥有，跳过：%s", name, link)
                        continue

                    selectors = [
                        'button:has-text("Get")','button:has-text("GET")',
                        'button:has-text("Claim")','button:has-text("CLAIM")',
                        'button:has-text("获取")','button:has-text("领取")',
                        '[role="button"]:has-text("Get")',
                        '[role="button"]:has-text("获取")',
                        'a:has-text("Get")','a:has-text("获取")'
                    ]

                    if not click_candidates(page, selectors):
                        continue

                    time.sleep(2)
                    click_candidates(page, [
                        'button:has-text("Place Order")',
                        'button:has-text("Place order")',
                        'button:has-text("Complete Purchase")',
                        'button:has-text("确认订单")',
                        'button:has-text("完成购买")'
                    ])
                    time.sleep(4)

                    if owned(page) or any(x in body_text(page) for x in [
                        "thank you", "thanks for your purchase", "谢谢"
                    ]):
                        success_count += 1
                        logger.info("[%s] 领取成功：%s", name, link)
                except Exception as e:
                    logger.warning("[%s] 候选处理失败：%s", name, e)

            logger.info("[%s] 本次完成，确认领取 %d 个。", name, success_count)
            return success_count
        finally:
            context.close()

def run_selected(app, accounts):
    if not accounts:
        app.set_status("没有启用任何账号")
        return
    app.set_status("正在运行...")
    for account in accounts:
        try:
            count = claim_account(account)
            app.set_status(f"{account['name']} 完成，确认领取 {count} 个")
        except Exception as e:
            logger.error("[%s] 失败：%s", account["name"], e)
            logger.error(traceback.format_exc())
            app.set_status(f"{account['name']} 失败")
    app.set_status("全部任务结束")

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Epic Auto Claim")
        self.geometry("900x650")
        self.minsize(820,580)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self.build_ui()
        self.refresh_from_config()

    def build_ui(self):
        style = ttk.Style(self)
        try: style.theme_use("vista")
        except Exception: pass

        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        ttk.Label(top, text="Epic Auto Claim", font=("Segoe UI", 20, "bold")).pack(side="left")
        self.status_var = tk.StringVar(value="就绪")
        ttk.Label(top, textvariable=self.status_var).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=12, pady=(0,12))

        self.dashboard = ttk.Frame(nb, padding=16)
        self.settings = ttk.Frame(nb, padding=16)
        nb.add(self.dashboard, text="控制面板")
        nb.add(self.settings, text="设置")

        # Dashboard
        self.edge_var = tk.BooleanVar()
        self.chrome_var = tk.BooleanVar()
        cards = ttk.LabelFrame(self.dashboard, text="账号", padding=12)
        cards.pack(fill="x")
        ttk.Checkbutton(cards, text="启用 Edge 账号", variable=self.edge_var).grid(row=0,column=0,padx=10,pady=8,sticky="w")
        ttk.Checkbutton(cards, text="启用 Chrome 账号", variable=self.chrome_var).grid(row=0,column=1,padx=10,pady=8,sticky="w")
        ttk.Label(cards,text="Edge/Chrome 使用独立 Profile，不保存 Epic 密码。").grid(row=1,column=0,columnspan=2,sticky="w",padx=10)

        actions = ttk.Frame(self.dashboard)
        actions.pack(fill="x", pady=15)
        ttk.Button(actions,text="立即领取",command=self.start_now).pack(side="left",padx=(0,8))
        ttk.Button(actions,text="保存设置",command=self.save_config).pack(side="left",padx=8)
        ttk.Button(actions,text="打开日志目录",command=self.open_logs).pack(side="left",padx=8)

        sched = ttk.LabelFrame(self.dashboard,text="自动任务",padding=12)
        sched.pack(fill="x")
        self.schedule_enabled = tk.BooleanVar()
        ttk.Checkbutton(sched,text="启用每周自动领取",variable=self.schedule_enabled).grid(row=0,column=0,sticky="w")
        self.day_var = tk.StringVar()
        self.time_var = tk.StringVar()
        ttk.Label(sched,text="星期").grid(row=1,column=0,pady=8,sticky="w")
        ttk.Combobox(sched,textvariable=self.day_var,values=["MON","TUE","WED","THU","FRI","SAT","SUN"],state="readonly",width=8).grid(row=1,column=1,sticky="w")
        ttk.Label(sched,text="时间").grid(row=1,column=2,padx=(25,5),sticky="w")
        ttk.Entry(sched,textvariable=self.time_var,width=10).grid(row=1,column=3,sticky="w")

        logframe = ttk.LabelFrame(self.dashboard,text="运行日志",padding=8)
        logframe.pack(fill="both",expand=True,pady=(15,0))
        self.log_text = tk.Text(logframe,wrap="none",font=("Consolas",9))
        self.log_text.pack(fill="both",expand=True)

        # Settings
        sf = ttk.LabelFrame(self.settings,text="浏览器与运行",padding=12)
        sf.pack(fill="x")
        self.headless_var = tk.BooleanVar()
        ttk.Checkbutton(sf,text="无头模式（后台运行，不显示浏览器）",variable=self.headless_var).pack(anchor="w")
        ttk.Label(sf,text="建议首次登录和排错时关闭无头模式。").pack(anchor="w",pady=(5,0))

        pathf = ttk.LabelFrame(self.settings,text="数据目录",padding=12)
        pathf.pack(fill="x",pady=12)
        ttk.Label(pathf,text=str(BASE_DIR)).pack(anchor="w")
        ttk.Label(pathf,text="profiles/：保存两个独立登录状态；logs/：日志；screenshots/：异常截图。").pack(anchor="w",pady=(5,0))

        ttk.Button(self.settings,text="保存设置",command=self.save_config).pack(anchor="e")

    def refresh_from_config(self):
        cfg = load_config()
        self.edge_var.set(cfg["accounts"][0].get("enabled",True))
        self.chrome_var.set(cfg["accounts"][1].get("enabled",True))
        self.schedule_enabled.set(cfg.get("schedule",{}).get("enabled",True))
        self.day_var.set(cfg.get("schedule",{}).get("day","THU"))
        self.time_var.set(cfg.get("schedule",{}).get("time","18:00"))
        self.headless_var.set(cfg.get("headless",False))

    def save_config(self):
        cfg = load_config()
        cfg["accounts"][0]["enabled"] = self.edge_var.get()
        cfg["accounts"][1]["enabled"] = self.chrome_var.get()
        cfg["schedule"] = {
            "enabled": self.schedule_enabled.get(),
            "day": self.day_var.get(),
            "time": self.time_var.get()
        }
        cfg["headless"] = self.headless_var.get()
        CONFIG_FILE.write_text(json.dumps(cfg,ensure_ascii=False,indent=4),encoding="utf-8")
        logger.info("设置已保存。")
        messagebox.showinfo("设置","设置已保存。")

    def selected_accounts(self):
        accounts = []
        if self.edge_var.get():
            accounts.append({"name":"Edge账号","browser":"edge","enabled":True})
        if self.chrome_var.get():
            accounts.append({"name":"Chrome账号","browser":"chrome","enabled":True})
        return accounts

    def start_now(self):
        self.save_config()
        accounts = self.selected_accounts()
        threading.Thread(target=run_selected,args=(self,accounts),daemon=True).start()

    def set_status(self,text):
        self.after(0, lambda:self.status_var.set(text))

    def append_log(self,text):
        self.log_text.insert("end",text+"\n")
        self.log_text.see("end")

    def open_logs(self):
        os.startfile(str(LOG_DIR))

if __name__ == "__main__":
    handler = None
    app = App()
    handler = GuiLogHandler(app)
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(handler)
    app.mainloop()
