import json
import logging
import os
import re
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

from playwright.sync_api import (
    sync_playwright,
    TimeoutError as PlaywrightTimeoutError
)


# ============================================================
# 路径
# ============================================================

BASE_DIR = Path(__file__).resolve().parent

CONFIG_FILE = BASE_DIR / "config.json"
PROFILE_DIR = BASE_DIR / "profiles"
LOG_DIR = BASE_DIR / "logs"
SCREENSHOT_DIR = BASE_DIR / "screenshots"

PROFILE_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)
SCREENSHOT_DIR.mkdir(exist_ok=True)


# ============================================================
# 日志
# ============================================================

log_file = LOG_DIR / f"{datetime.now():%Y-%m-%d}.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(
            log_file,
            encoding="utf-8"
        ),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("EpicAutoClaim")


# ============================================================
# 配置
# ============================================================

def load_config():
    if not CONFIG_FILE.exists():
        logger.error("找不到 config.json")
        sys.exit(1)

    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


CONFIG = load_config()

TIMEOUT = CONFIG.get(
    "claim",
    {}
).get(
    "timeout",
    30000
)

RETRY = CONFIG.get(
    "claim",
    {}
).get(
    "retry",
    3
)

WAIT_AFTER_CLICK = CONFIG.get(
    "claim",
    {}
).get(
    "wait_after_click",
    2500
)


# ============================================================
# Epic
# ============================================================

EPIC_STORE = "https://store.epicgames.com/"

EPIC_FREE_GAMES = (
    "https://store.epicgames.com/en-US/free-games"
)


# ============================================================
# 浏览器
# ============================================================

def get_browser_executable(browser_name):

    if browser_name.lower() == "edge":
        candidates = [
            os.environ.get(
                "PROGRAMFILES(X86)",
                r"C:\Program Files (x86)"
            )
            + r"\Microsoft\Edge\Application\msedge.exe",

            os.environ.get(
                "PROGRAMFILES",
                r"C:\Program Files"
            )
            + r"\Microsoft\Edge\Application\msedge.exe"
        ]

    elif browser_name.lower() == "chrome":
        candidates = [
            os.environ.get(
                "PROGRAMFILES",
                r"C:\Program Files"
            )
            + r"\Google\Chrome\Application\chrome.exe",

            os.environ.get(
                "PROGRAMFILES(X86)",
                r"C:\Program Files (x86)"
            )
            + r"\Google\Chrome\Application\chrome.exe",

            os.path.expandvars(
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
            )
        ]

    else:
        raise RuntimeError(
            f"未知浏览器：{browser_name}"
        )

    for path in candidates:
        if path and Path(path).exists():
            return path

    raise RuntimeError(
        f"没有找到 {browser_name} 浏览器"
    )


def create_profile(browser_name):

    path = PROFILE_DIR / browser_name.lower()
    path.mkdir(
        parents=True,
        exist_ok=True
    )

    return str(path)


# ============================================================
# 截图
# ============================================================

def screenshot(page, account_name, suffix):

    safe_name = re.sub(
        r'[\\/:*?"<>| ]+',
        "_",
        account_name
    )

    filename = (
        f"{datetime.now():%Y%m%d_%H%M%S}_"
        f"{safe_name}_{suffix}.png"
    )

    path = SCREENSHOT_DIR / filename

    try:
        page.screenshot(
            path=str(path),
            full_page=True
        )

        logger.info(
            "截图：%s",
            path
        )

    except Exception as e:
        logger.warning(
            "截图失败：%s",
            e
        )


# ============================================================
# 页面等待
# ============================================================

def wait_page(page, seconds=2):

    try:
        page.wait_for_load_state(
            "domcontentloaded",
            timeout=TIMEOUT
        )
    except Exception:
        pass

    time.sleep(seconds)


# ============================================================
# 登录检查
# ============================================================

def is_login_page(page):

    url = page.url.lower()

    login_keywords = [
        "login",
        "id/login",
        "signin",
        "account/signin"
    ]

    return any(
        keyword in url
        for keyword in login_keywords
    )


def wait_for_manual_login(
    page,
    account_name
):

    logger.warning(
        "[%s] 需要登录 Epic。",
        account_name
    )

    print()
    print("=" * 70)
    print(f"{account_name} 需要登录 Epic")
    print("请在打开的浏览器窗口中完成登录。")
    print("如果出现验证码/二次验证，请人工完成。")
    print("完成后程序会自动继续。")
    print("=" * 70)
    print()

    start = time.time()

    while time.time() - start < 300:

        try:

            url = page.url.lower()

            if (
                "login" not in url
                and "signin" not in url
            ):

                # 再给页面一点时间
                time.sleep(3)

                logger.info(
                    "[%s] 检测到登录流程结束。",
                    account_name
                )

                return True

        except Exception:
            pass

        time.sleep(2)

    return False


def ensure_login(
    page,
    account_name
):

    page.goto(
        EPIC_STORE,
        wait_until="domcontentloaded",
        timeout=TIMEOUT
    )

    wait_page(page, 3)

    if is_login_page(page):

        return wait_for_manual_login(
            page,
            account_name
        )

    # 页面上检查登录按钮
    login_texts = [
        "Sign In",
        "登录",
        "SIGN IN"
    ]

    for text in login_texts:

        try:

            locator = page.get_by_text(
                text,
                exact=True
            )

            if locator.count() > 0:

                logger.info(
                    "[%s] 可能尚未登录。",
                    account_name
                )

                return wait_for_manual_login(
                    page,
                    account_name
                )

        except Exception:
            pass

    logger.info(
        "[%s] 当前看起来已经登录。",
        account_name
    )

    return True


# ============================================================
# 获取免费游戏页面
# ============================================================

def open_free_games(page):

    logger.info(
        "打开 Epic 免费游戏页面..."
    )

    page.goto(
        EPIC_FREE_GAMES,
        wait_until="domcontentloaded",
        timeout=TIMEOUT
    )

    wait_page(page, 4)

    return page


# ============================================================
# CAPTCHA / 验证检测
# ============================================================

def detect_verification(page):

    content = ""

    try:
        content = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        ).lower()
    except Exception:
        return False

    keywords = [
        "captcha",
        "verify you are human",
        "验证您是人类",
        "安全验证",
        "robot",
        "机器人",
        "two-factor",
        "two factor",
        "二步验证"
    ]

    for keyword in keywords:

        if keyword.lower() in content:

            logger.warning(
                "检测到可能需要人工验证：%s",
                keyword
            )

            return True

    return False


# ============================================================
# 获取按钮
# ============================================================

def get_button_candidates(page):

    selectors = [

        # 英文
        'button:has-text("Get")',
        'button:has-text("GET")',
        'button:has-text("Claim")',
        'button:has-text("CLAIM")',

        # 中文
        'button:has-text("获取")',
        'button:has-text("领取")',

        # 通用
        '[role="button"]:has-text("Get")',
        '[role="button"]:has-text("获取")',
        '[role="button"]:has-text("领取")',

        'a:has-text("Get")',
        'a:has-text("获取")',
        'a:has-text("领取")'
    ]

    return selectors


def click_first_valid(
    page,
    selectors
):

    for selector in selectors:

        try:

            locator = page.locator(
                selector
            )

            count = locator.count()

            if count == 0:
                continue

            for i in range(
                min(count, 10)
            ):

                item = locator.nth(i)

                try:

                    if not item.is_visible():
                        continue

                    if not item.is_enabled():
                        continue

                    logger.info(
                        "尝试点击：%s",
                        selector
                    )

                    item.scroll_into_view_if_needed()

                    time.sleep(0.5)

                    item.click(
                        timeout=5000
                    )

                    return True

                except Exception:
                    continue

        except Exception:
            continue

    return False


# ============================================================
# 判断已经领取
# ============================================================

def is_already_owned(page):

    try:

        body = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        ).lower()

    except Exception:
        return False

    owned_keywords = [
        "in library",
        "owned",
        "已在库中",
        "已拥有",
        "已领取",
        "library"
    ]

    for keyword in owned_keywords:

        if keyword.lower() in body:

            logger.info(
                "检测到游戏可能已经在库中：%s",
                keyword
            )

            return True

    return False


# ============================================================
# 订单确认
# ============================================================

def confirm_order(page):

    logger.info(
        "检查订单确认页面..."
    )

    time.sleep(
        WAIT_AFTER_CLICK / 1000
    )

    # 常见的免费订单确认按钮
    selectors = [

        'button:has-text("Place Order")',
        'button:has-text("Place order")',
        'button:has-text("Complete Purchase")',

        'button:has-text("确认订单")',
        'button:has-text("下单")',
        'button:has-text("完成购买")',

        '[role="button"]:has-text("Place Order")',
        '[role="button"]:has-text("确认订单")'
    ]

    clicked = click_first_valid(
        page,
        selectors
    )

    if clicked:

        logger.info(
            "已点击订单确认按钮。"
        )

        time.sleep(4)

        return True

    return False


# ============================================================
# 领取当前页面游戏
# ============================================================

def claim_current_game(
    page,
    account_name
):

    if detect_verification(page):

        screenshot(
            page,
            account_name,
            "verification"
        )

        logger.warning(
            "[%s] 页面需要人工验证。",
            account_name
        )

        input(
            f"\n[{account_name}] "
            "请在浏览器中完成验证，然后按 Enter 继续..."
        )

    if is_already_owned(page):

        logger.info(
            "[%s] 当前游戏已经领取，跳过。",
            account_name
        )

        return True

    selectors = get_button_candidates(
        page
    )

    if not click_first_valid(
        page,
        selectors
    ):

        logger.warning(
            "[%s] 没有找到获取/领取按钮。",
            account_name
        )

        screenshot(
            page,
            account_name,
            "no_get_button"
        )

        return False

    logger.info(
        "[%s] 已点击获取按钮。",
        account_name
    )

    time.sleep(
        WAIT_AFTER_CLICK / 1000
    )

    # 尝试确认订单
    confirm_order(page)

    time.sleep(4)

    if is_already_owned(page):

        logger.info(
            "[%s] 领取成功/游戏已经在库中。",
            account_name
        )

        return True

    # 再检查页面文字
    try:

        text = page.locator(
            "body"
        ).inner_text(
            timeout=5000
        ).lower()

        success_keywords = [
            "thank you",
            "thanks for your purchase",
            "in library",
            "owned",
            "已在库中",
            "已拥有",
            "已领取",
            "谢谢"
        ]

        for keyword in success_keywords:

            if keyword in text:

                logger.info(
                    "[%s] 检测到领取成功标志：%s",
                    account_name,
                    keyword
                )

                return True

    except Exception:
        pass

    return False


# ============================================================
# 查找免费游戏
# ============================================================

def find_free_game_links(page):

    logger.info(
        "分析免费游戏页面..."
    )

    links = []

    try:

        anchors = page.locator(
            "a[href]"
        )

        count = anchors.count()

        logger.info(
            "页面发现 %d 个链接。",
            count
        )

        for i in range(
            min(count, 500)
        ):

            try:

                a = anchors.nth(i)

                href = a.get_attribute(
                    "href"
                )

                if not href:
                    continue

                href_lower = href.lower()

                if (
                    "/p/" in href_lower
                    or "/game/" in href_lower
                ):

                    if href.startswith("/"):
                        href = (
                            "https://store.epicgames.com"
                            + href
                        )

                    if href not in links:

                        links.append(href)

            except Exception:
                continue

    except Exception as e:

        logger.error(
            "分析免费游戏失败：%s",
            e
        )

    return links


# ============================================================
# 领取账号
# ============================================================

def run_account(
    account,
    playwright
):

    account_name = account["name"]
    browser_name = account["browser"]

    logger.info(
        ""
    )

    logger.info(
        "=" * 70
    )

    logger.info(
        "开始处理：%s",
        account_name
    )

    logger.info(
        "浏览器：%s",
        browser_name
    )

    logger.info(
        "=" * 70
    )

    executable = get_browser_executable(
        browser_name
    )

    profile = create_profile(
        browser_name
    )

    logger.info(
        "浏览器：%s",
        executable
    )

    logger.info(
        "Profile：%s",
        profile
    )

    context = None

    try:

        context = playwright.chromium.launch_persistent_context(

            user_data_dir=profile,

            executable_path=executable,

            headless=CONFIG.get(
                "headless",
                False
            ),

            viewport={
                "width": 1440,
                "height": 900
            },

            locale="zh-CN",

            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-notifications"
            ]
        )

        if len(context.pages) > 0:
            page = context.pages[0]
        else:
            page = context.new_page()

        page.set_default_timeout(
            TIMEOUT
        )

        # ----------------------------------------------------
        # 登录
        # ----------------------------------------------------

        if not ensure_login(
            page,
            account_name
        ):

            logger.error(
                "[%s] 登录失败。",
                account_name
            )

            screenshot(
                page,
                account_name,
                "login_failed"
            )

            return False

        # ----------------------------------------------------
        # 免费游戏页面
        # ----------------------------------------------------

        open_free_games(
            page
        )

        # ----------------------------------------------------
        # CAPTCHA
        # ----------------------------------------------------

        if detect_verification(
            page
        ):

            screenshot(
                page,
                account_name,
                "verification"
            )

            input(
                f"\n[{account_name}] "
                "检测到人工验证，请完成后按 Enter..."
            )

        # ----------------------------------------------------
        # 找游戏
        # ----------------------------------------------------

        links = find_free_game_links(
            page
        )

        logger.info(
            "[%s] 找到 %d 个可能的游戏链接。",
            account_name,
            len(links)
        )

        if not links:

            logger.warning(
                "[%s] 没有找到游戏链接。",
                account_name
            )

            screenshot(
                page,
                account_name,
                "no_games"
            )

            return False

        # ----------------------------------------------------
        # 逐个尝试
        #
        # Epic 免费页面通常同时存在：
        # 本周免费
        # 下周预告
        # DLC
        #
        # 所以这里只尝试前几个候选。
        # ----------------------------------------------------

        processed = 0

        for link in links:

            if processed >= 6:
                break

            processed += 1

            logger.info(
                "[%s] 打开候选游戏：%s",
                account_name,
                link
            )

            try:

                page.goto(
                    link,
                    wait_until="domcontentloaded",
                    timeout=TIMEOUT
                )

                wait_page(
                    page,
                    3
                )

                if detect_verification(
                    page
                ):

                    screenshot(
                        page,
                        account_name,
                        "verification_game"
                    )

                    input(
                        f"\n[{account_name}] "
                        "请完成验证后按 Enter..."
                    )

                # 已拥有
                if is_already_owned(
                    page
                ):

                    logger.info(
                        "[%s] 游戏已拥有，跳过。",
                        account_name
                    )

                    continue

                # 尝试领取
                success = False

                for retry in range(
                    1,
                    RETRY + 1
                ):

                    logger.info(
                        "[%s] 第 %d/%d 次领取尝试。",
                        account_name,
                        retry,
                        RETRY
                    )

                    try:

                        success = claim_current_game(
                            page,
                            account_name
                        )

                        if success:
                            break

                    except Exception as e:

                        logger.warning(
                            "领取异常：%s",
                            e
                        )

                        screenshot(
                            page,
                            account_name,
                            f"claim_error_{retry}"
                        )

                        time.sleep(2)

                if success:

                    logger.info(
                        "[%s] 当前游戏处理完成。",
                        account_name
                    )

                else:

                    logger.info(
                        "[%s] 当前候选未能确认领取。",
                        account_name
                    )

            except Exception as e:

                logger.error(
                    "[%s] 游戏处理失败：%s",
                    account_name,
                    e
                )

                screenshot(
                    page,
                    account_name,
                    "game_error"
                )

        logger.info(
            "[%s] 账号处理结束。",
            account_name
        )

        return True

    except Exception as e:

        logger.error(
            "[%s] 浏览器启动/运行失败：%s",
            account_name,
            e
        )

        logger.error(
            traceback.format_exc()
        )

        return False

    finally:

        if context:

            try:
                context.close()
            except Exception:
                pass


# ============================================================
# 主程序
# ============================================================

def main():

    logger.info(
        "=" * 70
    )

    logger.info(
        "Epic Auto Claim 启动"
    )

    logger.info(
        "时间：%s",
        datetime.now()
    )

    logger.info(
        "=" * 70
    )

    accounts = CONFIG.get(
        "accounts",
        []
    )

    if not accounts:

        logger.error(
            "config.json 中没有账号配置。"
        )

        return

    results = []

    with sync_playwright() as playwright:

        for account in accounts:

            if not account.get(
                "enabled",
                True
            ):
                continue

            try:

                result = run_account(
                    account,
                    playwright
                )

                results.append(
                    (
                        account["name"],
                        result
                    )
                )

            except Exception as e:

                logger.error(
                    "%s 执行异常：%s",
                    account["name"],
                    e
                )

                results.append(
                    (
                        account["name"],
                        False
                    )
                )

    logger.info(
        ""
    )

    logger.info(
        "=" * 70
    )

    logger.info(
        "本次执行结果"
    )

    logger.info(
        "=" * 70
    )

    for name, result in results:

        logger.info(
            "%s : %s",
            name,
            "完成" if result else "失败"
        )

    logger.info(
        "Epic Auto Claim 结束"
    )


if __name__ == "__main__":

    try:
        main()

    except KeyboardInterrupt:

        logger.info(
            "用户终止程序。"
        )

    except Exception:

        logger.error(
            traceback.format_exc()
        )

    finally:

        print()
        print(
            "程序执行结束。"
        )
        print(
            f"日志：{log_file}"
        )