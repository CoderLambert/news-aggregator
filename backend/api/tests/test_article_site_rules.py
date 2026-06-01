from api.services.article_fetcher.extractors import extract_markdown_from_html
from api.services.article_fetcher.site_rules import get_site_rule


def test_site_rule_matches_registered_domains_and_subdomains():
    assert get_site_rule('https://www.theregister.com/2026/01/01/story/').name == 'The Register'
    assert get_site_rule('https://techcrunch.com/2026/01/01/story/').name == 'TechCrunch'
    assert get_site_rule('https://dev.to/example/post').name == 'DEV Community'
    assert get_site_rule('https://github.com/org/repo/blob/main/README.md').name == 'GitHub'
    assert get_site_rule('https://www.bbc.co.uk/news/article').name == 'BBC'
    assert get_site_rule('https://www.reuters.com/world/story/').name == 'Reuters'
    assert get_site_rule('https://news.ycombinator.com/item?id=123').name == 'Hacker News'
    assert get_site_rule('https://www.producthunt.com/products/example-product').name == 'Product Hunt'
    assert get_site_rule('https://example.com/story') is None


def test_the_register_rule_extracts_body_and_removes_chrome():
    html = '''
    <html><head><title>Wrong chrome title</title></head><body>
      <nav>Navigation Subscribe cookie preferences</nav>
      <main>
        <article>
          <h1>The Register headline</h1>
          <div class="article_body">
            <p>The first Register paragraph contains concrete reporting and enough detail.</p>
            <p>The second Register paragraph continues the real article body for readers.</p>
            <div class="newsletter-signup">Subscribe to our newsletter</div>
          </div>
        </article>
      </main>
      <footer>Footer links and cookie settings</footer>
    </body></html>
    '''

    result = extract_markdown_from_html(html, 'https://www.theregister.com/2026/01/01/story/')

    assert result.title == 'The Register headline'
    assert 'first Register paragraph' in result.markdown
    assert 'second Register paragraph' in result.markdown
    assert 'Navigation Subscribe' not in result.markdown
    assert 'newsletter' not in result.markdown.lower()
    assert 'Footer links' not in result.markdown
    assert 'cookie preferences' not in result.markdown


def test_techcrunch_rule_extracts_article_content_and_removes_subscribe_cookie():
    html = '''
    <html><body>
      <header>TechCrunch menu and subscribe links</header>
      <article>
        <h1>TechCrunch headline</h1>
        <div class="article-content">
          <p>TechCrunch body paragraph one explains the funding news and product context.</p>
          <p>TechCrunch body paragraph two adds market background and founder comments.</p>
          <aside class="subscribe">Subscribe popup should be removed</aside>
          <div class="cookie-banner">We use cookies</div>
        </div>
      </article>
      <footer>Footer navigation</footer>
    </body></html>
    '''

    result = extract_markdown_from_html(html, 'https://techcrunch.com/2026/01/01/startup/')

    assert result.title == 'TechCrunch headline'
    assert 'funding news' in result.markdown
    assert 'founder comments' in result.markdown
    assert 'subscribe' not in result.markdown.lower()
    assert 'cookies' not in result.markdown.lower()
    assert 'Footer navigation' not in result.markdown


def test_devto_rule_extracts_markdown_body_and_removes_site_chrome():
    html = '''
    <html><body>
      <nav>DEV nav links</nav>
      <main>
        <article>
          <h1>DEV post headline</h1>
          <div id="article-body" class="crayons-article__body">
            <p>DEV article paragraph one describes the implementation step by step.</p>
            <p>DEV article paragraph two includes code discussion and lessons learned.</p>
            <div class="crayons-subscription">Subscribe to author updates</div>
          </div>
        </article>
      </main>
      <footer>DEV footer</footer>
    </body></html>
    '''

    result = extract_markdown_from_html(html, 'https://dev.to/example/implementation-notes')

    assert result.title == 'DEV post headline'
    assert 'implementation step by step' in result.markdown
    assert 'lessons learned' in result.markdown
    assert 'DEV nav links' not in result.markdown
    assert 'Subscribe to author' not in result.markdown
    assert 'DEV footer' not in result.markdown


def test_hacker_news_rule_extracts_self_post_without_comments():
    html = '''
    <html><head><title>Ask HN: Practical testing?</title></head><body>
      <center><table>
        <tr class="athing"><td class="title"><span class="titleline"><a href="item?id=123">Ask HN: Practical testing?</a></span></td></tr>
        <tr><td class="subtext">42 points by alice | hide | past | favorite | 18 comments</td></tr>
        <tr><td><div class="toptext">
          <p>I am looking for practical testing workflows that keep production code honest.</p>
          <p>What patterns helped your team avoid regressions while moving quickly?</p>
        </div></td></tr>
        <tr class="comment-tree"><td><span class="comment">This is a long comment that must not become full_content.</span></td></tr>
      </table></center>
    </body></html>
    '''

    result = extract_markdown_from_html(html, 'https://news.ycombinator.com/item?id=123')

    assert result.title == 'Ask HN: Practical testing?'
    assert 'practical testing workflows' in result.markdown
    assert 'avoid regressions' in result.markdown
    assert 'long comment' not in result.markdown
    assert '42 points' not in result.markdown


def test_producthunt_rule_extracts_product_body_and_removes_page_chrome():
    html = '''
    <html><head><title>SocialEcho 2.0 - Product Hunt</title></head><body>
      <header>Product Hunt navigation Login Sign up</header>
      <main>
        <section class="styles_productHero__abc">
          <h1>SocialEcho 2.0</h1>
          <p>Turn customer conversations into actionable product insights.</p>
          <p>SocialEcho helps founders understand feedback, prioritize roadmap ideas, and share launch updates with their community.</p>
          <a href="https://www.producthunt.com/r/p/123?app_id=339">Visit website</a>
        </section>
        <section class="comments">Great launch! This comment thread should not be treated as the product description.</section>
      </main>
      <footer>Footer links and newsletter signup</footer>
    </body></html>
    '''

    result = extract_markdown_from_html(html, 'https://www.producthunt.com/products/socialecho')

    assert result.title == 'SocialEcho 2.0'
    assert 'actionable product insights' in result.markdown
    assert 'prioritize roadmap ideas' in result.markdown
    assert 'Product Hunt navigation' not in result.markdown
    assert 'newsletter signup' not in result.markdown
    assert 'comment thread' not in result.markdown


def test_producthunt_rule_prefers_product_hero_over_long_discussion_sections():
    long_discussion = ' '.join(['This discussion text should not be selected as the product body.'] * 80)
    html = f'''
    <html><head><title>SignalDesk - Product Hunt</title></head><body>
      <main>
        <section class="styles_productHero__abc">
          <h1>SignalDesk</h1>
          <p>Coordinate launch messaging, user interviews, and roadmap updates from one focused workspace.</p>
          <p>Teams use SignalDesk to turn launch feedback into prioritized product decisions.</p>
        </section>
        <section data-test="discussion-feed">
          <h2>Community discussion</h2>
          <p>{long_discussion}</p>
        </section>
      </main>
    </body></html>
    '''

    result = extract_markdown_from_html(html, 'https://www.producthunt.com/products/signaldesk')

    assert result.title == 'SignalDesk'
    assert 'Coordinate launch messaging' in result.markdown
    assert 'prioritized product decisions' in result.markdown
    assert 'discussion text should not be selected' not in result.markdown
