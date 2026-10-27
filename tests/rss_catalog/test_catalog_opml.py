"""Offline parser/merge contracts; no Django configuration or network required."""
import copy
import importlib
import json
import unittest
from xml.etree import ElementTree as ET


def module():
    try:
        return importlib.import_module('api.rss.catalog_opml')
    except ModuleNotFoundError:
        raise AssertionError('Default-catalog OPML implementation is missing') from None


def opml(paths=None):
    paths = paths or [('技术', 'AI / 大模型', 'https://publisher.example/feed', 'AI feed')]
    root = ET.Element('opml', version='2.0')
    body = ET.SubElement(root, 'body')
    for section, group, url, name in paths:
        outer = ET.SubElement(body, 'outline', text=section)
        inner = ET.SubElement(outer, 'outline', text=group)
        ET.SubElement(inner, 'outline', text=name, type='rss', xmlUrl=url, language='en')
    return ET.tostring(root, encoding='utf-8')


SOURCE = {'id': 'user-curated', 'commit': 'a'*64, 'license': 'NOASSERTION',
          'url': 'https://github.com/CoderLambert/news-aggregator'}


def old_entry(url='https://publisher.example/feed', **changes):
    row = dict(name='Original title', description='Original attribution', language='en', region='',
               tags=['Engineering & Technology'], public_url=url, kind='feed', visibility='public',
               required_parameters=[], capability_requirements=[], verified_at=None,
               origin={**SOURCE, 'id': 'old-catalog', 'key': 'upstream-key'})
    row.update(changes)
    return row


class CatalogParserTests(unittest.TestCase):
    def parse(self, raw=None, **kw):
        return module().parse_catalog_opml(raw or opml(), validate_url=lambda url: url, minimum=0, **kw)

    def test_preserves_slashes_as_label_not_extra_depth(self):
        result = self.parse()
        self.assertEqual(len(result), 1)
        self.assertIn('newshub:tech:ai-llm', result[0]['tags'])
        self.assertEqual(result[0]['language'], 'en')
        self.assertNotIn('verified_at', result[0])

    def test_duplicate_url_merges_group_membership(self):
        rows = self.parse(opml([('技术','AI / 大模型','https://publisher.example/feed','One'),
                                ('技术','前端开发','https://PUBLISHER.example:443/feed','Two')]))
        self.assertEqual(len(rows), 1)
        self.assertIn('newshub:tech:frontend', rows[0]['tags'])
        self.assertIn('newshub:tech:ai-llm', rows[0]['tags'])

    def test_query_and_trailing_slash_are_not_guessed_aliases(self):
        urls = ['https://p.example/feed', 'https://p.example/feed/', 'https://p.example/feed?a=1', 'https://p.example/feed?a=2']
        rows = self.parse(opml([('技术','前端开发',u,'Feed') for u in urls]))
        self.assertEqual(len(rows), 4)

    def test_uses_existing_url_validator_for_every_outline(self):
        seen = []
        def reject(value):
            seen.append(value)
            raise ValueError('blocked by URL policy')
        with self.assertRaisesRegex(ValueError, 'blocked'):
            module().parse_catalog_opml(opml(), validate_url=reject, minimum=0)
        self.assertEqual(seen, ['https://publisher.example/feed'])

    def test_unknown_taxonomy_is_rejected(self):
        for path in [('其他','AI / 大模型'), ('技术','不存在')]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.parse(opml([(*path,'https://p.example/rss','Feed')]))

    def test_no_flattening_or_ungrouped_import(self):
        for raw in [b'<opml><body><outline xmlUrl="https://p.example/rss"/></body></opml>',
                    b'<opml><body><outline text="tech / AI"><outline xmlUrl="https://p.example/rss"/></outline></body></opml>']:
            with self.subTest(raw=raw), self.assertRaises(ValueError): self.parse(raw)

    def test_entities_doctype_and_wrong_root_are_rejected(self):
        for raw in [b'<!DOCTYPE opml [<!ENTITY x SYSTEM "file:///etc/passwd">]><opml><body>&x;</body></opml>',
                    b'<rss><channel/></rss>', b'<opml><body>', b'<opml/>']:
            with self.subTest(raw=raw), self.assertRaises(ValueError): self.parse(raw)

    def test_byte_limit_is_enforced_before_parsing(self):
        with self.assertRaises(ValueError): self.parse(b' ' * (module().MAX_BYTES + 1))

    def test_feed_with_nested_children_is_rejected(self):
        raw = opml().replace(b' />', b'><outline text="surprise"/></outline>')
        with self.assertRaises(ValueError): self.parse(raw)

    def test_names_are_not_silently_truncated(self):
        with self.assertRaises(ValueError): self.parse(opml([('技术','前端开发','https://p.example/rss','x'*256)]))

    def test_each_group_minimum_includes_absent_groups(self):
        with self.assertRaisesRegex(ValueError, 'minimum'):
            module().parse_catalog_opml(opml(), validate_url=lambda x:x, minimum=20)

    def test_large_global_catalog_does_not_use_personal_500_limit(self):
        rows = self.parse(opml([('技术','前端开发',f'https://p{i}.example/rss','Feed') for i in range(502)]))
        self.assertEqual(len(rows), 502)

    def test_taxonomy_is_exactly_five_sections_twenty_one_groups(self):
        taxonomy = importlib.import_module('api.rss.catalog_taxonomy')
        self.assertEqual(len(taxonomy.SECTIONS), 5)
        self.assertEqual(sum(len(s['groups']) for s in taxonomy.SECTIONS), 21)


class CatalogMergeTests(unittest.TestCase):
    def incoming(self):
        return module().parse_catalog_opml(opml(), validate_url=lambda x:x, minimum=0)

    def test_merges_without_replacing_existing_identity_and_metadata(self):
        old = old_entry(); before=copy.deepcopy(old)
        document, report = module().merge_catalog([old], self.incoming(), SOURCE)
        row = document['collections'][0]['entries'][0]
        self.assertEqual(row['name'], 'Original title')
        self.assertEqual(row['key'], 'upstream-key')
        self.assertEqual(document['collections'][0]['source']['id'], 'old-catalog')
        self.assertIn('newshub:tech:ai-llm', row['tags'])
        self.assertEqual(report['added'], 0)
        self.assertEqual(report['reused'], 1)
        self.assertEqual(old, before)

    def test_retains_unrelated_entries_and_route_templates(self):
        template=old_entry('/github/issue/:owner/:repo', kind='route_template',
                           required_parameters=['owner','repo'], origin={**SOURCE,'id':'rsshub','key':'route'})
        document, report=module().merge_catalog([old_entry('https://old.example/rss'),template],self.incoming(),SOURCE)
        rows=[x for c in document['collections'] for x in c['entries']]
        self.assertEqual(len(rows),3)
        self.assertIn(template['public_url'],[r['public_url'] for r in rows])
        self.assertEqual(report['added'],1)

    def test_hidden_entries_are_never_resurrected(self):
        document, report=module().merge_catalog([old_entry(visibility='hidden')],self.incoming(),SOURCE)
        rows=[x for c in document['collections'] for x in c['entries']]
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['visibility'],'hidden')
        self.assertEqual(report['suppressed'],1)
        self.assertNotIn('newshub:tech:ai-llm', rows[0]['tags'])

    def test_repeated_import_is_byte_stable(self):
        first,_=module().merge_catalog([old_entry()],self.incoming(),SOURCE)
        existing=[dict(r,origin={**c['source'],'key':r['key']}) for c in first['collections'] for r in c['entries']]
        second,report=module().merge_catalog(existing,self.incoming(),SOURCE)
        self.assertEqual(module().encode_snapshot(first),module().encode_snapshot(second))
        self.assertEqual(report['added'],0)

    def test_order_changes_do_not_change_snapshot_checksum(self):
        rows=[old_entry('https://a.example/rss'),old_entry('https://b.example/rss',origin={**SOURCE,'id':'legacy2','key':'b'})]
        a,_=module().merge_catalog(rows,self.incoming(),SOURCE)
        b,_=module().merge_catalog(list(reversed(rows)),self.incoming(),SOURCE)
        self.assertEqual(module().encode_snapshot(a),module().encode_snapshot(b))

    def test_counts_use_unique_feed_urls_not_template_or_hidden(self):
        taxonomy=importlib.import_module('api.rss.catalog_taxonomy')
        row=dict(public_url='https://p.example/rss',kind='feed',visibility='public',tags=['newshub:tech:ai-llm','newshub:tech:frontend'])
        tree=taxonomy.taxonomy_counts([row,copy.deepcopy(row),dict(row,visibility='hidden'),dict(row,kind='route_template')])
        tech=next(s for s in tree if s['key']=='tech')
        self.assertEqual(tech['count'],1)
        self.assertEqual(next(g for g in tech['groups'] if g['key']=='ai-llm')['count'],1)

    def test_filter_rejects_mismatched_section_and_group(self):
        taxonomy=importlib.import_module('api.rss.catalog_taxonomy')
        with self.assertRaises(ValueError): taxonomy.validate_selection('business','frontend')
        with self.assertRaises(ValueError): taxonomy.validate_selection('missing','')
        self.assertEqual(taxonomy.validate_selection('tech','frontend'),None)


if __name__ == '__main__': unittest.main()
