"""Follow-up browser acceptance: T20 failure-recovery scenarios omitted from
the original T27 script. Synthetic-only: route interception injects failures
against the local synthetic Miniflux/temp-DB stack started by run_browser.py.
No public fetching and no real keys. Assertions are not weakened: each scenario
checks the user-visible error, the exact retry control, and request counts.
"""
import json
from pathlib import Path
import sys
import time
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
expect.set_options(timeout=20000)

config = json.loads(Path(sys.argv[1]).read_text())
assert config['project'].startswith('newshub-rss-t27-')
assert urlsplit(config['origin']).hostname == '127.0.0.1'
output = Path(config['output']); output.mkdir(parents=True, exist_ok=True)
errors, checks = [], {}
phase = 'startup'
counts = {'discovery_post': 0, 'discovery_result_get': 0, 'subscribe_post': 0, 'directory_get': 0}
subscribe_keys = []
state = {'discovery_fail': None, 'discovery_result_fail': True, 'subscribe_fail': None, 'directory_subscribed_fixture': False}

CANDIDATE = {'url': 'https://publisher.example:8443/feed/discovered-0', 'title': 'Candidate 0', 'candidate_token': 'qa-token-0'}

with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
        args=['--no-sandbox', '--disable-dev-shm-usage'])
    context = browser.new_context(viewport={'width': 1440, 'height': 1000})
    page = context.new_page()
    page.on('pageerror', lambda error: errors.append(str(error)))

    def handle_discovery(route):
        counts['discovery_post'] += 1
        fail = state['discovery_fail']
        if fail == '400':
            state['discovery_fail'] = None
            route.fulfill(status=400, content_type='application/json', body=json.dumps({'detail': 'synthetic discovery 400'}))
        elif fail == 'timeout':
            state['discovery_fail'] = None
            time.sleep(22)  # exceeds the client's 20s workspace timeout
            try: route.fulfill(status=500, content_type='application/json', body='{}')
            except Exception: pass
        elif fail == 'poll':
            state['discovery_fail'] = None
            route.fulfill(status=200, content_type='application/json',
                          body=json.dumps({'operation_id': 'qa-poll-op', 'state': 'pending'}))
        else:
            route.continue_()

    def handle_poll_get(route):
        counts['discovery_result_get'] += 1
        if state['discovery_result_fail']:
            route.fulfill(status=500, content_type='application/json', body=json.dumps({'detail': 'synthetic result 500'}))
        else:
            route.fulfill(status=200, content_type='application/json', body=json.dumps({
                'state': 'succeeded', 'result': {'operation_id': 'qa-poll-op', 'state': 'succeeded', 'candidates': [CANDIDATE]}}))

    def handle_subscribe(route):
        if route.request.method != 'POST':
            route.continue_(); return
        counts['subscribe_post'] += 1
        subscribe_keys.append(route.request.headers.get('idempotency-key'))
        fail = state['subscribe_fail']
        if fail == '400':
            state['subscribe_fail'] = None
            route.fulfill(status=400, content_type='application/json', body=json.dumps({'detail': 'synthetic subscribe 400'}))
        elif fail == 'timeout':
            state['subscribe_fail'] = None
            time.sleep(22)
            try: route.fulfill(status=500, content_type='application/json', body='{}')
            except Exception: pass
        else:
            route.continue_()

    def handle_directory(route):
        counts['directory_get'] += 1
        if not state['directory_subscribed_fixture']:
            route.continue_(); return
        response = route.fetch()
        data = response.json()
        data['results'] = [{
            'id': 'qa-already-entry', 'name': 'T27 Synthetic Already Subscribed',
            'description': 'Local synthetic feed, pre-subscribed in this run',
            'kind': 'feed', 'public_url': 'https://publisher.example:8443/feed/already-subscribed',
            'executable': True, 'subscribed': True, 'cached_articles': []}] + list(data.get('results') or [])
        route.fulfill(status=200, content_type='application/json', body=json.dumps(data))

    page.route('**/api/rss/discovery/resolve/', handle_discovery)
    page.route('**/api/me/rss-operations/qa-poll-op/', handle_poll_get)
    page.route('**/api/me/rss-subscriptions/', handle_subscribe)
    page.route('**/api/rss/directory/**', handle_directory)

    def login(username):
        page.get_by_role('button', name='登录', exact=True).first.click()
        page.locator('#auth-username').fill(username)
        page.locator('#auth-password').fill('Synthetic-T27-pass-123')
        page.locator('#auth-password').press('Enter')
        expect(page.get_by_role('img', name=username + '，已登录')).to_be_visible(timeout=15000)

    def open_dialog():
        page.get_by_role('button', name='添加频道', exact=True).click()
        dialog = page.get_by_role('dialog', name='添加订阅')
        expect(dialog).to_be_visible()
        return dialog

    def close_dialog(dialog):
        page.keyboard.press('Escape')
        expect(dialog).not_to_be_visible()

    def submit(dialog, value):
        dialog.get_by_label('搜索订阅源、网站或 RSS 地址').fill(value)
        dialog.get_by_role('button', name='查找订阅', exact=True).click()

    def screenshot(name):
        page.screenshot(path=str(output / name), full_page=True)

    try:
        page.goto(config['origin'] + '/', wait_until='networkidle')
        login('t27_alice')
        page.goto(config['origin'] + '/channels', wait_until='networkidle')

        # --- Already-subscribed: real local subscription first (pre-seed), then
        # a synthetic directory entry for that same local feed is returned with
        # the backend's subscribed flag (backend marking itself is covered by
        # backend/api/tests/rss/test_directory_http.py). Radio must be disabled.
        phase = 'already_subscribed'
        dialog = open_dialog()
        submit(dialog, 'https://publisher.example:8443/feed/already-subscribed')
        expect(dialog.get_by_text('已选择订阅，请确认分组。', exact=True)).to_be_visible()
        dialog.get_by_role('button', name='确认订阅', exact=True).click()
        expect(dialog.get_by_text('来源已连接，首次文章同步将在后台完成。', exact=True)).to_be_visible(timeout=25000)
        dialog.get_by_role('button', name='完成', exact=True).click()
        state['directory_subscribed_fixture'] = True
        dialog = open_dialog()
        before_sub = counts['subscribe_post']
        submit(dialog, 'Synthetic Already')
        expect(dialog.get_by_text('T27 Synthetic Already Subscribed', exact=True)).to_be_visible()
        expect(dialog.get_by_text('已订阅', exact=True)).to_be_visible()
        radio = dialog.get_by_role('radio')
        expect(radio.first).to_be_disabled()
        expect(dialog.get_by_role('button', name='确认订阅', exact=True)).to_be_disabled()
        assert counts['subscribe_post'] == before_sub, counts
        checks['already_subscribed_radio_disabled_no_resubscribe'] = True
        screenshot('followup-01-already-subscribed.png')
        state['directory_subscribed_fixture'] = False
        close_dialog(dialog)

        # --- Discovery result GET failure: only re-read GET, never re-POST.
        phase = 'discovery_result_get_failure'
        dialog = open_dialog()
        state['discovery_fail'] = 'poll'; state['discovery_result_fail'] = True
        submit(dialog, 'https://publisher.example:8443/one')
        expect(dialog.get_by_text('发现结果读取失败', exact=False)).to_be_visible(timeout=20000)
        post_after_fail, get_after_fail = counts['discovery_post'], counts['discovery_result_get']
        assert get_after_fail >= 1
        state['discovery_result_fail'] = False
        dialog.get_by_role('button', name='重新读取发现结果', exact=True).click()
        expect(dialog.get_by_role('radio')).to_have_count(1, timeout=20000)
        assert counts['discovery_post'] == post_after_fail, counts
        assert counts['discovery_result_get'] > get_after_fail, counts
        checks['discovery_result_get_failure_only_rereads'] = {'post': counts['discovery_post'], 'get': counts['discovery_result_get']}
        screenshot('followup-02-discovery-get-recovery.png')
        close_dialog(dialog)

        # --- Discovery HTTP 400, then retry via its own control.
        phase = 'discovery_400'
        dialog = open_dialog()
        state['discovery_fail'] = '400'
        post0 = counts['discovery_post']
        submit(dialog, 'https://publisher.example:8443/one')
        expect(dialog.get_by_text('发现请求未完成', exact=False)).to_be_visible()
        expect(dialog.get_by_text('synthetic discovery 400', exact=False)).to_be_visible()
        dialog.get_by_role('button', name='重新查找订阅', exact=True).click()
        expect(dialog.get_by_role('radio')).to_have_count(1, timeout=25000)
        assert counts['discovery_post'] == post0 + 2, counts
        checks['discovery_400_visible_and_retry'] = True
        close_dialog(dialog)

        # --- Discovery long timeout (>20s client timeout), then retry.
        phase = 'discovery_timeout'
        dialog = open_dialog()
        state['discovery_fail'] = 'timeout'
        post0 = counts['discovery_post']
        submit(dialog, 'https://publisher.example:8443/one')
        expect(dialog.get_by_text('发现请求未完成', exact=False)).to_be_visible(timeout=35000)
        dialog.get_by_role('button', name='重新查找订阅', exact=True).click()
        expect(dialog.get_by_role('radio')).to_have_count(1, timeout=25000)
        assert counts['discovery_post'] == post0 + 2, counts
        checks['discovery_timeout_visible_and_retry'] = True
        screenshot('followup-03-discovery-timeout-retry.png')
        close_dialog(dialog)

        # --- Subscribe HTTP 400, then retry-same-request control.
        phase = 'subscribe_400'
        dialog = open_dialog()
        state['subscribe_fail'] = '400'
        submit(dialog, 'https://publisher.example:8443/feed/qa-400')
        expect(dialog.get_by_text('已选择订阅，请确认分组。', exact=True)).to_be_visible()
        dialog.get_by_role('button', name='确认订阅', exact=True).click()
        expect(dialog.get_by_text('订阅保存结果未确认', exact=False)).to_be_visible()
        expect(dialog.get_by_text('synthetic subscribe 400', exact=False)).to_be_visible()
        keys_before_retry = list(subscribe_keys)
        dialog.get_by_role('button', name='重试保存订阅', exact=True).click()
        expect(dialog.get_by_text('订阅已保存', exact=False)).to_be_visible(timeout=25000)
        assert subscribe_keys[-1] == keys_before_retry[-1] and keys_before_retry[-1], subscribe_keys
        checks['subscribe_400_visible_and_retry_same_idempotency'] = True
        dialog.get_by_role('button', name='完成', exact=True).click()

        # --- Subscribe long timeout, then retry-same-request control.
        phase = 'subscribe_timeout'
        dialog = open_dialog()
        state['subscribe_fail'] = 'timeout'
        submit(dialog, 'https://publisher.example:8443/feed/qa-timeout')
        expect(dialog.get_by_text('已选择订阅，请确认分组。', exact=True)).to_be_visible()
        dialog.get_by_role('button', name='确认订阅', exact=True).click()
        expect(dialog.get_by_text('订阅保存结果未确认', exact=False)).to_be_visible(timeout=35000)
        keys_before_retry = list(subscribe_keys)
        dialog.get_by_role('button', name='重试保存订阅', exact=True).click()
        expect(dialog.get_by_text('订阅已保存', exact=False)).to_be_visible(timeout=25000)
        assert subscribe_keys[-1] == keys_before_retry[-1] and keys_before_retry[-1], subscribe_keys
        checks['subscribe_timeout_visible_and_retry_same_idempotency'] = True
        screenshot('followup-04-subscribe-timeout-retry.png')
        dialog.get_by_role('button', name='完成', exact=True).click()

        checks['counts'] = counts
        checks['browser_errors'] = errors
        assert not errors, errors
        result = {'tested_sha': config['tested_sha'], 'project': config['project'], 'checks': checks,
                  'browser': browser.version, 'status': 'passed'}
        (output / 'followup-evidence.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        try: screenshot('followup-failure.png')
        except Exception: pass
        (output / 'followup-failure.json').write_text(json.dumps({'phase': phase, 'error': str(error), 'checks': checks,
            'counts': counts, 'body': page.locator('body').inner_text()[:12000], 'page_errors': errors}, ensure_ascii=False, indent=2))
        raise
    finally:
        browser.close()
