"""Browser smoke check and screenshots for the standalone BYOK design prototype.

Usage: python3 docs/features/byok/prototype/check_ui.py
Dependencies: pip install playwright ; python -m playwright install chromium
This checks only local mock interactions. NEVER enter a real API key.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUTPUT = HERE / "screenshots"
OUTPUT.mkdir(parents=True, exist_ok=True)
HTML = (HERE / "index.html").read_text(encoding="utf-8")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
    errors = []
    page = browser.new_page(viewport={"width": 1440, "height": 1050}, device_scale_factor=1)
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.set_content(HTML, wait_until="load")
    assert "AI 模型与密钥" in page.title()
    page.screenshot(path=str(OUTPUT / "byok-settings-desktop.png"), full_page=True)

    page.get_by_role("tab", name="服务商连接").click()
    page.screenshot(path=str(OUTPUT / "byok-connections-desktop.png"), full_page=True)
    page.locator('.vendor-card[data-provider="anthropic"]').click()
    assert page.locator("#connection-form").count() == 1
    page.screenshot(path=str(OUTPUT / "byok-add-connection-desktop.png"), full_page=True)
    page.locator("#key-field").fill("DEMO-NOT-A-REAL-KEY")
    page.locator('#connection-form button[type="submit"]').click()
    assert page.get_by_text("Claude · 个人").count() > 0

    page.get_by_role("tab", name="模型与用途").click()
    page.locator("#pref-chat").select_option("m2")
    assert "尚未保存" in page.locator(".saving-bar").inner_text()
    page.get_by_role("button", name="保存用途偏好").click()
    assert "已保存的偏好" in page.locator(".saving-bar").inner_text()

    page.get_by_role("tab", name="文章内体验预览").click()
    page.locator("#preview-model").select_option("m3")
    page.get_by_role("button", name="展示模拟结果").click()
    assert page.get_by_text("演示内容").count() > 0
    page.screenshot(path=str(OUTPUT / "byok-article-preview-desktop.png"), full_page=True)

    mobile = browser.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=1)
    mobile.on("pageerror", lambda error: errors.append(str(error)))
    mobile.set_content(HTML, wait_until="load")
    mobile.screenshot(path=str(OUTPUT / "byok-settings-mobile.png"), full_page=True)
    mobile.get_by_role("tab", name="服务商连接").click()
    mobile.screenshot(path=str(OUTPUT / "byok-connections-mobile.png"), full_page=True)
    assert mobile.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

    empty = browser.new_page(viewport={"width": 1100, "height": 900})
    empty.on("pageerror", lambda error: errors.append(str(error)))
    empty.set_content(HTML, wait_until="load")
    empty.get_by_role("button", name="查看空账户状态").click()
    assert empty.get_by_text("还没有可以分配的模型").count() > 0
    empty.screenshot(path=str(OUTPUT / "byok-empty-state.png"), full_page=True)
    assert not errors, errors
    browser.close()

print("BYOK prototype smoke: PASS (mock-only); screenshots:", OUTPUT)
