#!/usr/bin/env python3
"""Guided headed Playwright UAT for live NewsHub (Chinese UI).

Walks login → research → translation → TTS → Xiaowen chat → AI model settings.
Secrets only via env; never hardcoded. Soft-skips paid steps when key/UI missing.
"""
from __future__ import annotations

import os
import re
import sys
import time
from urllib.parse import urlsplit

try:
    from playwright.sync_api import sync_playwright, expect, TimeoutError as PlaywrightTimeout
except ImportError:
    print('缺少 playwright。请先: python3 -m pip install "playwright>=1.40" && python3 -m playwright install chromium', file=sys.stderr)
    sys.exit(1)

BASE = os.environ.get('NEWSHUB_BASE_URL', 'http://127.0.0.1:9527').rstrip('/')
USER = os.environ.get('NEWSHUB_ACCEPTANCE_USER', '')
PASSWORD = os.environ.get('NEWSHUB_ACCEPTANCE_PASSWORD', '')
DEEPSEEK_KEY = os.environ.get('NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY', '')
CHROMIUM = os.environ.get('NEWSHUB_ACCEPTANCE_CHROMIUM', '')
PAUSE = os.environ.get('NEWSHUB_ACCEPTANCE_PAUSE', '1') != '0'
SLOW_MO = int(os.environ.get('NEWSHUB_ACCEPTANCE_SLOW_MO', '400'))
ARTICLE_PATH = os.environ.get('NEWSHUB_ACCEPTANCE_ARTICLE_PATH', '')

SOFT_FAILS: list[str] = []
HARD_FAILS: list[str] = []


def log(msg: str) -> None:
    print(f'[UAT] {msg}', flush=True)


def section(title: str) -> None:
    print('\n' + '=' * 60, flush=True)
    print(f'▶ {title}', flush=True)
    print('=' * 60, flush=True)


def pause(hint: str) -> None:
    if not PAUSE:
        time.sleep(1.2)
        return
    try:
        input(f'\n⏸  {hint}\n   按回车继续… ')
    except EOFError:
        time.sleep(1.5)


def soft(msg: str) -> None:
    SOFT_FAILS.append(msg)
    log(f'软跳过/软失败：{msg}')


def hard(msg: str) -> None:
    HARD_FAILS.append(msg)
    log(f'硬失败：{msg}')


def require_host() -> None:
    host = urlsplit(BASE).hostname
    if host not in ('127.0.0.1', 'localhost'):
        hard(f'出于安全，BASE_URL 主机必须是 127.0.0.1/localhost，当前={host!r}')
        sys.exit(1)


def login(page) -> bool:
    section('1. 登录')
    if not USER or not PASSWORD:
        soft('未设置 NEWSHUB_ACCEPTANCE_USER / NEWSHUB_ACCEPTANCE_PASSWORD，跳过登录及后续登录态步骤')
        pause('请手动登录后，若继续请确保已登录；否则后续会软失败')
        return False
    page.goto(BASE + '/', wait_until='domcontentloaded')
    # already logged in?
    if page.get_by_role('button', name='打开菜单', exact=True).count():
        log('检测到已登录会话，跳过登录表单')
        pause('确认当前登录身份无误')
        return True
    btn = page.get_by_role('button', name='登录', exact=True).first
    expect(btn).to_be_visible(timeout=15000)
    btn.click()
    page.locator('#auth-username').fill(USER)
    page.locator('#auth-password').fill(PASSWORD)
    page.locator('#auth-password').press('Enter')
    try:
        expect(page.get_by_role('button', name='打开菜单', exact=True)).to_be_visible(timeout=20000)
        log('登录成功')
    except PlaywrightTimeout:
        # avatar alt pattern used in T27
        try:
            expect(page.get_by_role('img', name=re.compile(re.escape(USER)))).to_be_visible(timeout=5000)
            log('登录成功（头像可见）')
        except PlaywrightTimeout:
            hard('登录失败：未看到登录后菜单/头像')
            return False
    pause('观察登录后首页')
    return True


def open_first_article(page) -> bool:
    if ARTICLE_PATH:
        page.goto(BASE + ARTICLE_PATH, wait_until='domcontentloaded')
        return True
    page.goto(BASE + '/', wait_until='domcontentloaded')
    # Prefer a news link
    link = page.locator('a[href^="/news/"]').first
    try:
        expect(link).to_be_visible(timeout=15000)
        href = link.get_attribute('href') or ''
        log(f'打开文章 {href}')
        link.click()
        page.wait_for_url(re.compile(r'.*/news/\d+'), timeout=15000)
        return True
    except PlaywrightTimeout:
        soft('首页未找到文章链接，翻译/语音/小闻将跳过')
        return False


def step_research(page) -> None:
    section('2. 深度研究')
    page.goto(BASE + '/', wait_until='domcontentloaded')
    btn = page.get_by_role('button', name='打开新闻研究助手', exact=True)
    try:
        expect(btn).to_be_visible(timeout=10000)
        btn.click()
        # panel chrome
        expect(page.get_by_role('button', name='新建研究', exact=True)).to_be_visible(timeout=15000)
        log('深度研究面板已打开')
        pause('观察深度研究面板；可选手动输入问题（脚本不自动发起付费研究）')
        page.get_by_role('button', name='关闭', exact=True).first.click()
    except PlaywrightTimeout:
        soft('未找到「打开新闻研究助手」或研究面板未就绪（功能开关/登录态？）')


def step_translation(page) -> None:
    section('3. 文章翻译')
    if not open_first_article(page):
        return
    panel = page.get_by_label('全文翻译')
    try:
        expect(panel).to_be_visible(timeout=15000)
        log('已定位全文翻译控件')
        # Do not auto-click translate (paid); show operator the button
        btn = panel.get_by_role('button').filter(has_text=re.compile('翻译')).first
        if btn.count():
            log(f'翻译按钮文案：{(btn.inner_text() or "").strip()[:40]}')
        pause('可选手动点击「翻译为中文 / 重新翻译」观察流式译文；脚本默认不自动付费翻译')
    except PlaywrightTimeout:
        soft('当前文章未见「全文翻译」区域（可能无正文/未登录/能力关闭）')


def step_tts(page) -> None:
    section('4. 语音生成')
    if '/news/' not in page.url:
        if not open_first_article(page):
            return
    btn = page.get_by_role('button', name='选择语音播报方式', exact=True)
    try:
        expect(btn).to_be_visible(timeout=10000)
        btn.click()
        expect(page.get_by_label('语音播报设置')).to_be_visible(timeout=10000)
        log('语音播报设置已打开')
        pause('可选手动选择语言/范围并开始朗读；脚本默认不自动触发生成')
        # close if still open
        closer = page.get_by_role('button', name='关闭语音设置', exact=True)
        if closer.count():
            closer.click()
    except PlaywrightTimeout:
        soft('未找到语音播报入口（TTS 能力关闭或文章页结构变化）')


def step_xiaowen(page) -> None:
    section('5. 小闻问答')
    if '/news/' not in page.url:
        if not open_first_article(page):
            return
    btn = page.get_by_role('button', name='询问 AI 助手小闻', exact=True)
    try:
        expect(btn).to_be_visible(timeout=10000)
        btn.click()
        box = page.get_by_role('textbox', name='输入聊天问题')
        expect(box).to_be_visible(timeout=15000)
        log('小闻对话窗口已打开')
        pause('可选手动提问；脚本默认不自动发送付费消息')
        closer = page.get_by_role('button', name='关闭对话窗口', exact=True)
        if closer.count():
            closer.click()
    except PlaywrightTimeout:
        soft('小闻入口或输入框未出现（默认模型未配置/登录态？）')


def step_model_config(page) -> None:
    section('6. 模型配置（DeepSeek 文本 + 工具验证）')
    page.goto(BASE + '/settings/ai', wait_until='domcontentloaded')
    try:
        expect(page.get_by_text(re.compile('DeepSeek|deepseek'), exact=False).first).to_be_visible(timeout=15000)
    except PlaywrightTimeout:
        soft('AI 设置页未见 DeepSeek 连接')
        pause('检查 /settings/ai')
        return

    # Optional: replace key via UI if env key present
    # Prefer the DeepSeek card's「替换 Key」button (AIModelSettingsPage).
    if DEEPSEEK_KEY:
        log('检测到 NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY，尝试通过 UI「替换 Key」（不打印密钥）')
        try:
            card = page.locator('div').filter(has_text=re.compile(r'deepseek', re.I)).filter(
                has=page.get_by_role('button', name='替换 Key', exact=True)).first
            replace = card.get_by_role('button', name='替换 Key', exact=True) if card.count() else page.get_by_role('button', name='替换 Key', exact=True).first
            if replace.count():
                replace.click()
                expect(page.get_by_text('替换连接 Key', exact=True)).to_be_visible(timeout=10000)
                key_input = page.locator('input[type="password"]').last
                key_input.fill(DEEPSEEK_KEY)
                page.get_by_role('button', name='保存连接', exact=True).click()
                page.wait_for_timeout(1000)
                log('已提交 Key 更新（以页面回馈为准）')
            else:
                soft('未找到「替换 Key」按钮；请手动粘贴 Key 后继续探针')
                pause('请手动完成 DeepSeek Key 保存')
        except Exception as exc:  # noqa: BLE001 — guided soft path
            soft(f'替换 Key UI 流程异常：{type(exc).__name__}')
            pause('请手动保存 DeepSeek Key 后回车继续探针')
    else:
        soft('未设置 NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY，跳过自动换 Key；若连接已有有效 Key 仍可测探针')

    def run_probe(label: str, button_name: str, badge_re: re.Pattern, toast_re: re.Pattern) -> None:
        btn = page.get_by_role('button', name=button_name, exact=True).first
        try:
            expect(btn).to_be_visible(timeout=10000)
            btn.click()
            log(f'已点击「{button_name}」，等待结果…')
            # Prefer status toast, fall back to capability badge text.
            try:
                expect(page.get_by_text(toast_re).first).to_be_visible(timeout=120000)
            except PlaywrightTimeout:
                expect(page.get_by_text(badge_re).first).to_be_visible(timeout=5000)
            log(f'{label}：通过（UI 显示已验证支持）')
        except PlaywrightTimeout:
            soft(f'{label}：未在时限内看到成功文案（可能网关/额度/模型问题）')

    pause('确认 DeepSeek 连接可见后回车，开始文本探针')
    run_probe(
        '文本能力', '测试文本能力',
        re.compile(r'文本：已验证支持'),
        re.compile(r'文本能力测试通过，已验证支持'),
    )
    pause('观察文本结果后回车，开始工具探针')
    run_probe(
        '工具能力', '测试工具能力',
        re.compile(r'工具调用：已验证支持'),
        re.compile(r'工具调用能力测试通过，已验证支持'),
    )
    pause('模型配置段结束')


def main() -> int:
    require_host()
    log(f'BASE={BASE} pause={PAUSE} slow_mo={SLOW_MO} deepseek_key={"set" if DEEPSEEK_KEY else "absent"}')
    launch_kwargs = {
        'headless': False,
        'slow_mo': SLOW_MO,
        'args': ['--no-sandbox', '--disable-dev-shm-usage'],
    }
    if CHROMIUM:
        launch_kwargs['executable_path'] = CHROMIUM
    elif os.path.isfile('/usr/bin/chromium'):
        launch_kwargs['executable_path'] = '/usr/bin/chromium'

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**launch_kwargs)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, locale='zh-CN')
        page = context.new_page()
        page.set_default_timeout(20000)
        try:
            logged_in = login(page)
            if HARD_FAILS:
                return 1
            if logged_in or USER:
                step_research(page)
                step_translation(page)
                step_tts(page)
                step_xiaowen(page)
                step_model_config(page)
            else:
                soft('无登录态，仅完成到登录提示')
        except Exception as exc:  # noqa: BLE001
            hard(f'未捕获异常：{type(exc).__name__}: {exc}')
        finally:
            pause('全部段落结束，回车关闭浏览器')
            browser.close()

    print('\n—— 汇总 ——', flush=True)
    if HARD_FAILS:
        for item in HARD_FAILS:
            print(f'HARD: {item}', flush=True)
        return 1
    if SOFT_FAILS:
        for item in SOFT_FAILS:
            print(f'SOFT: {item}', flush=True)
        print('退出码 2（有软失败，便于区分全绿）', flush=True)
        return 2
    print('全部段落完成，无软失败。', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
