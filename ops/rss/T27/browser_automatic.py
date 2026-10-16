"""Normal non-admin direct subscription creates and extracts before first read."""
import json
import re
from pathlib import Path
import sys
import time
import traceback
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

expect.set_options(timeout=25000)
config = json.loads(Path(sys.argv[1]).read_text())
assert config['project'].startswith('newshub-rss-t27-')
assert urlsplit(config['origin']).hostname == '127.0.0.1'
output = Path(config['output'])
network = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True,
        args=['--no-sandbox', '--disable-dev-shm-usage'])
    page = browser.new_page(viewport={'width': 1440, 'height': 1000})
    page.on('request', lambda request: network.append({'method':request.method,'url':request.url,'time':time.time()})
        if '/api/' in request.url else None)
    page.route('https://publisher.example:8443/pixel.png', lambda route: route.fulfill(
        status=200, content_type='image/svg+xml', body='<svg xmlns="http://www.w3.org/2000/svg" width="320" height="100"><rect width="320" height="100" fill="#207a69"/><text x="20" y="56" fill="white" font-size="24">T27 synthetic image</text></svg>'))
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto(config['origin'] + '/channels', wait_until='networkidle')
        page.get_by_role('button', name='登录', exact=True).first.click()
        page.locator('#auth-username').fill('t27_bob')
        page.locator('#auth-password').fill('Synthetic-T27-pass-123')
        page.locator('#auth-password').press('Enter')
        expect(page.get_by_role('img', name='t27_bob，已登录')).to_be_visible()
        page.get_by_role('button', name='添加频道', exact=True).click()
        dialog = page.get_by_role('dialog', name='添加订阅')
        dialog.get_by_role('button', name='RSS 地址', exact=True).click()
        dialog.get_by_label('公开 RSS 地址').fill('https://publisher.example:8443/feed/auto-summary')
        dialog.get_by_role('button', name='选择地址', exact=True).click()
        started = time.monotonic()
        dialog.get_by_role('button', name='确认订阅', exact=True).click()
        expect(dialog.get_by_text('来源已连接，首次文章同步将在后台完成。', exact=True)).to_be_visible()
        connected = time.monotonic()
        dialog.get_by_role('button', name='完成', exact=True).click()
        first_news_read = time.time()
        article = None
        for _ in range(240):
            result = page.evaluate("""async()=>{
                const r=await fetch('/api/news/?mode=keyword&search=T27%20Connected%20auto-summary&representation=summary');
                if(!r.ok) throw Error('news '+r.status); return await r.json();
            }""")
            rows = result.get('results', []) if isinstance(result,dict) else result
            article = next((row for row in rows if row['title']=='T27 Connected auto-summary'),None)
            if article: break
            page.wait_for_timeout(250)
        assert article, result
        visible = time.monotonic()
        page.goto(config['origin'] + '/news/' + str(article['id']), wait_until='networkidle')
        expect(page.get_by_text('Expanded synthetic content. ' * 80, exact=True)).to_be_visible()
        expect(page.locator('pre code')).to_have_text('def greet(name):\n    # keep  two spaces\n    return f"hello {name}"\n')
        response = page.evaluate("async()=>await (await fetch('/api/me/rss-subscriptions/')).json()")
        rows = response.get('results', []) if isinstance(response,dict) else response
        subscription = next(row for row in rows if any(feed['feed_url'].endswith('/feed/auto-summary') for feed in row['feeds']))
        assert subscription['feeds'][0]['desired_mode']=='full_content', subscription
        assert subscription['publication']=='personal'
        assert not [row for row in network if '/rss-refetch/' in row['url'] or '/fetch-full/' in row['url'] or '/policy/' in row['url']]
        audit = [json.loads(line) for line in (Path(config['state_dir'])/'audit/requests.jsonl').read_text().splitlines()]
        article_requests = [row for row in audit if row['path']=='/article/auto-summary']
        assert article_requests and max(row['time'] for row in article_requests) < first_news_read
        assert not errors, errors
        page.screenshot(path=str(output/'automatic-summary.png'),full_page=True)
        page.get_by_text('Expanded synthetic content. ' * 80, exact=True).scroll_into_view_if_needed()
        page.screenshot(path=str(output/'automatic-expanded.png'),full_page=True)
        code_text = page.locator('pre code').text_content()
        code_layout = {}
        for theme, button in [('dark', '切换深色'), ('light', '切换浅色')]:
            page.get_by_role('button', name=button, exact=True).click()
            if theme == 'dark':
                expect(page.locator('html')).to_have_class(re.compile(r'.*dark.*'))
            else:
                expect(page.locator('html')).not_to_have_class(re.compile(r'.*dark.*'))
            # Lazy syntax highlighting can replace the code node; reacquire it in one DOM action.
            page.locator('pre code').evaluate("el=>el.scrollIntoView({block:'center',behavior:'instant'})")
            page.wait_for_function("()=>{const r=document.querySelector('pre code')?.getBoundingClientRect();return r && r.top>=0 && r.bottom<=innerHeight}")
            expect(page.locator('pre code')).to_have_text(code_text)
            code_layout[theme] = page.locator('pre code').evaluate("""el=>{
                const r=el.getBoundingClientRect(), s=getComputedStyle(el);
                return {width:r.width,height:r.height,color:s.color,visible:r.top>=0 && r.bottom<=innerHeight,
                    no_page_overflow:document.documentElement.scrollWidth<=innerWidth};
            }""")
            assert code_layout[theme]['visible'] and code_layout[theme]['no_page_overflow'], code_layout
            page.screenshot(path=str(output / ('automatic-' + theme + '.png')), full_page=True)
        assert code_layout['dark']['color'] != code_layout['light']['color'], code_layout
        page.get_by_role('button', name='打开目录', exact=True).click()
        toc = page.get_by_role('navigation', name='文章目录', exact=True)
        expect(toc.get_by_role('button', name='Expanded section', exact=True)).to_be_visible()
        target = page.get_by_role('heading', name='Closing section', exact=True)
        before = target.bounding_box()['y']
        toc.get_by_role('button', name='Closing section', exact=True).click()
        page.wait_for_function("""()=>{
            const h=[...document.querySelectorAll('h2')].find(e=>e.textContent==='Closing section');
            const r=h.getBoundingClientRect(); return r.top>=0 && r.bottom<=innerHeight;
        }""")
        after = target.bounding_box()['y']
        assert after < before, (before, after)
        page.screenshot(path=str(output/'automatic-toc.png'), full_page=True)
        assert not errors, errors
        result={'tested_sha':config['tested_sha'],'project':config['project'],'status':'passed',
            'actor':'non_admin_bob','default_mode':'full_content','gate_enabled':True,
            'no_explicit_policy_or_refetch':True,'article_requests_before_first_news_read':len(article_requests),
            'article_id':article['id'],'private_subscription':True,'expanded_body_visible':True,
            'theme_code_layout':code_layout,'theme_code_exact':True,
            'toc_navigation':{'heading':'Closing section','before_y':before,'after_y':after,'passed':True},
            'subscribe_to_connected_seconds':round(connected-started,3),
            'subscribe_to_visible_seconds':round(visible-started,3),'page_errors':errors}
        (output/'automatic-evidence.json').write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result))
    except Exception:
        (output/'automatic-error.txt').write_text(traceback.format_exc())
        page.screenshot(path=str(output/'automatic-failure.png'),full_page=True)
        (output/'automatic-failure.txt').write_text(page.locator('body').inner_text())
        raise
    finally:
        (output/'automatic-network.json').write_text(json.dumps(network,indent=2)+'\n')
        browser.close()
