"""Offline structural evidence for the two explicitly repeated public articles.

Raw publisher/engine HTML stays in the private /tmp directory, never in Git.
These comparisons support the accompanying human source-page review; they do
not promote any production completeness flag or directory verified badge.
"""
import argparse
import json
from pathlib import Path
import sys
from urllib.parse import urljoin
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'backend'))
from api.rss.content import convert_html

parser = argparse.ArgumentParser()
parser.add_argument('--bodies', type=Path, required=True)
parser.add_argument('--repeat-evidence', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
assert str(args.bodies).startswith('/tmp/newshub-rss-t27-quality-')
old = json.loads((ROOT / 'ops/rss/T27/evidence/public-samples.json').read_text())
repeat = json.loads(args.repeat_evidence.read_text())
norm = lambda text: ' '.join(text.split())
paragraphs = lambda node: [norm(p.get_text(' ', strip=True)) for p in node.find_all('p') if norm(p.get_text(' ', strip=True))]
rows = []
for name, slug in [('Julia Evans', 'julia'), ('Martin Fowler', 'fowler')]:
    entry = next(row for row in repeat['feeds'] if row['name'] == name)['entries'][0]
    original = next(item for row in old['feeds'] for item in row['entries'] if item['url'] == entry['url'])
    html = (args.bodies / (slug + '-engine.html')).read_text()
    engine = BeautifulSoup(html, 'html.parser')
    source = BeautifulSoup((args.bodies / (slug + '-source.html')).read_text(), 'html.parser')
    main = source.find('main')
    assert main
    assert convert_html(html, base_url=entry['url']).canonical_hash == entry['canonical_hash']
    row = {'source': name, 'url': entry['url'], 'canonical_hash': entry['canonical_hash'],
           'same_hash_as_initial_sample': entry['canonical_hash'] == original['canonical_hash'],
           'title_matches_source': norm(source.title.get_text()) == entry['title'],
           'reviewed_existing_sample': True, 'new_sample_denominator': 0,
           'source_body_selector': 'main', 'source_tables': len(main.find_all('table'))}
    if slug == 'julia':
        row.update(normalized_main_text_equal=norm(main.get_text(' ',strip=True)) == norm(engine.get_text(' ',strip=True)),
            heading_sequence_equal=[norm(x.get_text()) for x in main.find_all(['h1','h2','h3','h4'])] == [norm(x.get_text()) for x in engine.find_all(['h1','h2','h3','h4'])],
            headings=len(main.find_all(['h1','h2','h3','h4'])), paragraphs=len(paragraphs(main)),
            paragraph_sequence_equal=paragraphs(main)==paragraphs(engine),
            code_blocks=len(main.find_all('pre')),
            every_code_block_exact=[x.get_text() for x in main.find_all('pre')]==[x.get_text() for x in engine.find_all('pre')],
            manual_outcome='main_body_retained_in_this_sample')
    else:
        body = main.select_one('.paperBody')
        expected, actual = paragraphs(body), paragraphs(engine)
        indexes = [actual.index(text) if text in actual else -1 for text in expected]
        row.update(core_body_selector='main .paperBody', core_nonempty_paragraphs=len(expected),
            all_core_paragraphs_retained=all(index>=0 for index in indexes),
            core_paragraph_order_retained=indexes==sorted(indexes),
            source_core_headings=len(body.find_all(['h1','h2','h3','h4'])),
            source_core_images=len(body.find_all('img')),
            image_sequence_equal=[urljoin(entry['url'],x.get('src','')) for x in body.find_all('img')]==[x.get('src','') for x in engine.find_all('img')],
            normalized_main_text_equal=norm(main.get_text(' ',strip=True))==norm(engine.get_text(' ',strip=True)),
            manual_outcome='core_readable_but_incomplete_and_acknowledgments_reordered',
            omissions=['introductory_dek','author_biography','related_work','page_date_and_revision_metadata'],
            reordered=['acknowledgments_precedes_main_narrative_in_extracted_body'],
            date_observation={'feed_published_at':entry['published_at'],'source_visible_date':'2026-07-16'})
    rows.append(row)
args.output.write_text(json.dumps({'review_date':'2026-10-16','existing_samples_reviewed':2,
    'new_articles_added':0,'production_verified_flags_changed':False,'articles':rows},indent=2)+'\n')
