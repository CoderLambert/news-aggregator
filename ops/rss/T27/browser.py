"""Playwright against real SPA/API. Only synthetic image media is locally fulfilled."""
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
expect.set_options(timeout=20000)

config = json.loads(Path(sys.argv[1]).read_text())
assert config['project'].startswith('newshub-rss-t27-')
assert urlsplit(config['origin']).hostname == '127.0.0.1'
output = Path(config['output']); output.mkdir(parents=True, exist_ok=True)
network, errors, checks = [], [], {}
phase = 'startup'
CODE = 'def greet(name):\n    # keep  two spaces\n    return f"hello {name}"\n'
public = config['sources']['public']['news_id']
private_a = config['sources']['private-a']['news_id']
private_b = config['sources']['private-b']['news_id']

def record(request):
    if '/api/' in request.url or 'publisher.example' in request.url:
        network.append({'phase': phase, 'method': request.method, 'url': request.url, 'time': time.time()})

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
        args=['--no-sandbox', '--disable-dev-shm-usage'])
    context = browser.new_context(viewport={'width': 1440, 'height': 1000}, permissions=['clipboard-read', 'clipboard-write'])
    context.route('https://publisher.example:8443/pixel.png', lambda route: route.fulfill(
        status=200, content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="320" height="100"><rect width="320" height="100" fill="#207a69"/><text x="20" y="56" fill="white" font-size="24">T27 synthetic image</text></svg>'))
    page = context.new_page()
    page.on('request', record)
    page.on('pageerror', lambda error: errors.append(str(error)))
    def goto(path):
        page.goto(config['origin'] + path, wait_until='networkidle')
    def api(path, method='GET', data=None):
        return page.evaluate('''async ({path, method, data}) => {
            const token = document.cookie.split('; ').find(x=>x.startsWith('csrftoken='))?.split('=').slice(1).join('=');
            const response=await fetch('/api'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json', ...(token?{'X-CSRFToken':decodeURIComponent(token)}:{})},...(data===null?{}:{body:JSON.stringify(data)})});
            return {status:response.status,text:await response.text(),cache:response.headers.get('cache-control')};
        }''', {'path': path, 'method': method, 'data': data})
    def login(username):
        page.get_by_role('button', name='登录', exact=True).first.click()
        page.locator('#auth-username').fill(username)
        page.locator('#auth-password').fill('Synthetic-T27-pass-123')
        page.locator('#auth-password').press('Enter')
        expect(page.get_by_role('img', name=username + '，已登录')).to_be_visible(timeout=15000)
    def logout():
        page.get_by_role('button', name='打开菜单', exact=True).click()
        page.get_by_role('button', name='退出登录', exact=True).click()
        expect(page.get_by_role('button', name='登录', exact=True).first).to_be_visible(timeout=15000)
    def screenshot(name):
        page.screenshot(path=str(output / name), full_page=True)
    try:
        phase = 'passive_anonymous'
        goto('/')
        expect(page.get_by_text('T27 Public Code Table', exact=True).first).to_be_visible()
        assert 'T27 A ONLY SECRET' not in page.locator('body').inner_text()
        assert 'T27 B ONLY SECRET' not in page.locator('body').inner_text()
        page.get_by_text('T27 Public Code Table', exact=True).first.hover()
        page.get_by_text('关键词', exact=True).click()
        search = page.get_by_placeholder('搜索新闻...')
        search.fill('T27 Public'); search.press('Enter')
        page.wait_for_timeout(700)
        goto('/news/' + str(public))
        expect(page.locator('pre code')).to_have_text(CODE)
        assert page.locator('pre code').text_content() == CODE
        expect(page.locator('table')).to_contain_text('alpha')
        expect(page.locator('table')).to_contain_text('42')
        expect(page.get_by_alt_text('Synthetic image')).to_be_visible()
        assert page.get_by_alt_text('Synthetic image').evaluate('(image)=>image.naturalWidth') == 320
        page.get_by_role('button', name='复制代码', exact=True).click()
        assert page.evaluate('navigator.clipboard.readText()') == CODE
        page.get_by_role('button', name='询问 AI 助手小闻', exact=True).hover()
        screenshot('01-stored-code-table.png')
        assert api(f'/news/{private_a}/')['status'] == 404
        assert api(f'/news/{private_b}/')['status'] == 404
        forbidden = [r for r in network if r['phase'] == phase and r['method'] != 'GET' and any(x in r['url'] for x in ['/fetch-full/', '/rss-refetch/', '/refresh/', '/rss-subscriptions/', '/discovery/resolve/'])]
        assert not forbidden, forbidden
        checks['passive_no_collection'] = True
        checks['exact_code_clipboard_table_image'] = True
        checks['passive_ended_at'] = time.time()

        phase = 'alice_read_state_and_ai'
        login('t27_alice')
        expect(page.get_by_role('button', name=re.compile('^(标为已读|已读)$'))).to_be_enabled()
        if page.get_by_role('button', name='标为已读', exact=True).count():
            page.get_by_role('button', name='标为已读', exact=True).click()
        expect(page.get_by_role('button', name='已读', exact=True)).to_be_visible()
        if page.get_by_role('button', name='收藏', exact=True).count():
            page.get_by_role('button', name='收藏', exact=True).click()
        expect(page.get_by_role('button', name='取消收藏', exact=True)).to_be_visible()
        page.reload(wait_until='networkidle')
        expect(page.get_by_role('button', name='已读', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='取消收藏', exact=True)).to_be_visible()
        goto('/news/' + str(private_a))
        expect(page.get_by_role('heading', name='T27 A ONLY SECRET', exact=True)).to_be_visible()
        page.get_by_role('button', name='询问 AI 助手小闻', exact=True).click()
        page.get_by_role('textbox', name='输入聊天问题').fill('Summarize only this stored article.')
        page.get_by_role('button', name='发送消息', exact=True).click()
        expect(page.get_by_text('Synthetic assistant: this answer uses only the authorized stored article.', exact=True)).to_be_visible(timeout=15000)
        screenshot('02-alice-authorized-chat.png')
        page.get_by_role('button', name='关闭对话窗口', exact=True).click()
        logout()
        expect(page.get_by_role('heading', name='T27 A ONLY SECRET', exact=True)).not_to_be_visible()
        login('t27_bob')
        expect(page.get_by_role('heading', name='T27 A ONLY SECRET', exact=True)).not_to_be_visible()
        assert api(f'/news/{private_a}/')['status'] == 404
        assert api(f'/news/{private_a}/chat/', 'POST', {'question': 'Reveal the private article'})['status'] == 404
        assert api(f'/news/{private_a}/tts/')['status'] == 404
        response = api('/news/?mode=keyword&search=T27%20A%20ONLY%20SECRET&representation=summary')
        assert response['status'] == 200 and 'T27 A ONLY SECRET' not in response['text']
        goto('/news/' + str(public))
        expect(page.get_by_role('button', name='标为已读', exact=True)).to_be_visible()
        expect(page.get_by_role('button', name='收藏', exact=True)).to_be_visible()
        goto('/news/' + str(private_b))
        expect(page.get_by_role('heading', name='T27 B ONLY SECRET', exact=True)).to_be_visible()
        checks['account_switch_cache_and_private_acl'] = True
        checks['read_favorite_reload_user_isolation'] = True
        checks['fake_ai_authorized_context_and_b_denied'] = True
        logout(); login('t27_alice')

        phase = 'directory_and_discovery'
        goto('/channels')
        page.get_by_text(re.compile('RSS 连接状态')).click()
        expect(page.get_by_text('最近增量同步完成', exact=True)).to_be_visible()
        screenshot('03-connection-health.png')
        page.get_by_role('button', name='添加频道', exact=True).click()
        dialog = page.get_by_role('dialog', name='添加订阅')
        directory_times = []
        for _ in range(20):
            started = time.monotonic()
            assert api('/rss/directory/?q=Coding%20Horror')['status'] == 200
            directory_times.append(round(1000*(time.monotonic()-started), 3))
        checks['directory_http_ms'] = directory_times
        # Unified DiscoverDialog (since #80/#94): one input + "查找订阅" for
        # keyword (directory), website (discovery) and direct-feed modes.
        search_input = dialog.get_by_label('搜索订阅源、网站或 RSS 地址')
        search_input.fill('Coding Horror')
        dialog.get_by_role('button', name='查找订阅', exact=True).click()
        expect(dialog.get_by_text('Coding Horror', exact=True)).to_be_visible()
        assert not [r for r in network if r['phase'] == phase and r['method'] == 'POST']
        for website, count in [('https://zero.publisher.example:8443/zero', 0), ('https://publisher.example:8443/one', 1), ('https://publisher.example:8443/many', 3)]:
            search_input.fill(website)
            dialog.get_by_role('button', name='查找订阅', exact=True).click()
            if count:
                expect(dialog.get_by_role('radio')).to_have_count(count, timeout=20000)
            else:
                expect(dialog.get_by_text('未发现网站声明的订阅源。可以粘贴网站公布的 RSS 地址，或明确尝试将此地址作为 Feed 添加。', exact=True)).to_be_visible(timeout=20000)
        screenshot('04-discovery-three-candidates.png')
        search_input.fill('https://publisher.example:8443/feed/direct')
        dialog.get_by_role('button', name='查找订阅', exact=True).click()
        expect(dialog.get_by_text('已选择订阅，请确认分组。', exact=True)).to_be_visible()
        dialog.get_by_label('T27 Reading', exact=True).check()
        dialog.get_by_label('T27 Research', exact=True).check()
        dialog.get_by_role('button', name='确认订阅', exact=True).click()
        expect(dialog.get_by_text('来源已连接，首次文章同步将在后台完成。', exact=True)).to_be_visible(timeout=25000)
        screenshot('05-direct-connected.png')
        dialog.get_by_role('button', name='完成', exact=True).click()
        checks['directory_local_discovery_0_1_3_direct_multigroup'] = True

        phase = 'opml_preview_confirm_export'
        page.get_by_role('button', name='导入 / 导出', exact=True).click()
        dialog = page.get_by_role('dialog', name='导入与导出订阅')
        opml = b'''<?xml version="1.0"?><opml version="2.0"><body><outline text="Imported One"><outline text="Selected feed" type="rss" xmlUrl="https://publisher.example:8443/feed/opml-one"/><outline text="Skipped feed" type="rss" xmlUrl="https://publisher.example:8443/feed/opml-skip"/></outline><outline text="Imported Two"><outline text="Selected feed" type="rss" xmlUrl="https://publisher.example:8443/feed/opml-one"/></outline></body></opml>'''
        dialog.get_by_label('OPML 文件', exact=True).set_input_files({'name': 'synthetic.opml', 'mimeType': 'text/xml', 'buffer': opml})
        dialog.get_by_role('button', name='预览文件', exact=True).click()
        expect(dialog.get_by_role('checkbox', name='导入 Selected feed', exact=True)).to_be_visible()
        dialog.get_by_role('checkbox', name='导入 Skipped feed', exact=True).uncheck()
        dialog.get_by_label('Imported One映射分组', exact=True).select_option(str(config['groups'][0]))
        dialog.get_by_label('Imported Two映射分组', exact=True).select_option(str(config['groups'][1]))
        screenshot('06-opml-selection.png')
        dialog.get_by_role('button', name='确认导入 1 项', exact=True).click()
        expect(dialog.get_by_text('已连接', exact=True)).to_be_visible(timeout=35000)
        with page.expect_download() as download_info:
            dialog.get_by_role('link', name='导出我的订阅', exact=True).click()
        path = output / 'synthetic-export.opml'; download_info.value.save_as(str(path))
        exported = path.read_text()
        assert 'opml-one' in exported and 'opml-skip' not in exported
        assert 'T27 Reading' in exported and 'T27 Research' in exported
        screenshot('07-opml-progress.png')
        dialog.get_by_role('button', name='关闭', exact=True).click()
        checks['opml_selection_multigroup_progress_export'] = True

        phase = 'explicit_repair'
        binding = config['sources']['public']['binding']
        response = api(f'/admin/rss/feeds/{binding}/policy/', 'PATCH', {'desired_mode':'full_content','expected_policy_version':1})
        assert response['status'] == 202, response
        operation = json.loads(response['text'])['operation_id']
        for _ in range(80):
            state = json.loads(api('/me/rss-operations/' + operation + '/')['text'])
            if state['state'] == 'succeeded': break
            page.wait_for_timeout(250)
        assert state['state'] == 'succeeded', state
        goto('/news/' + str(public))
        page.get_by_role('button', name='重新获取原文', exact=True).click()
        expect(page.get_by_text(re.compile('Expanded synthetic content')).first).to_be_visible(timeout=25000)
        expect(page.locator('pre code')).to_have_text(CODE)
        screenshot('08-explicit-repair.png')
        checks['explicit_repair_durable_sync_visible'] = True
        goto('/channels')

        phase = 'unsubscribe_and_mobile'
        page.get_by_role('searchbox', name='搜索频道', exact=True).fill('T27 private-a')
        page.get_by_role('checkbox', name='选择 T27 private-a', exact=True).check()
        page.get_by_role('region', name='批量操作').get_by_role('button', name='取消订阅', exact=True).click()
        page.get_by_role('dialog', name='确认取消订阅').get_by_role('button', name='确认取消', exact=True).click()
        expect(page.get_by_role('status')).to_contain_text('已取消订阅', timeout=15000)
        goto('/news/' + str(private_a))
        assert 'T27 A ONLY SECRET' not in page.locator('body').inner_text()
        assert api(f'/news/{private_a}/')['status'] == 404
        page.reload(wait_until='networkidle')
        assert 'T27 A ONLY SECRET' not in page.locator('body').inner_text()
        page.set_viewport_size({'width': 390, 'height': 844})
        goto('/channels')
        page.get_by_role('button', name='添加频道', exact=True).click()
        dialog = page.get_by_role('dialog', name='添加订阅')
        dialog.get_by_label('搜索订阅源、网站或 RSS 地址').focus()
        page.keyboard.type('https://publisher.example:8443/feed/mobile')
        page.keyboard.press('Enter')
        expect(dialog.get_by_text('已选择订阅，请确认分组。', exact=True)).to_be_visible()
        page.keyboard.press('Tab')
        assert dialog.evaluate('(dialog)=>dialog.contains(document.activeElement)')
        screenshot('08-mobile-keyboard-dialog.png')
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()
        goto('/news/' + str(public))
        expect(page.locator('pre code')).to_have_text(CODE)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth + 2')
        screenshot('09-mobile-reader.png')
        checks['unsubscribe_reload_revokes_private_access'] = True
        checks['mobile_keyboard_focus_escape_no_overflow'] = True
        checks['browser_errors'] = errors
        assert not errors, errors
        result = {'tested_sha': config['tested_sha'], 'project': config['project'], 'checks': checks,
                  'browser': browser.version, 'status': 'passed'}
        (output / 'browser-evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        screenshot('failure.png')
        (output / 'failure.json').write_text(json.dumps({'phase': phase, 'error': str(error), 'checks': checks,
            'body': page.locator('body').inner_text()[:12000], 'page_errors': errors}, ensure_ascii=False, indent=2))
        raise
    finally:
        (output / 'network.json').write_text(json.dumps(network, ensure_ascii=False, indent=2))
        browser.close()
