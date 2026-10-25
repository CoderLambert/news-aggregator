"""Offline Agent configuration regressions; never calls a model, DB or network."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location('newshub_agent_rules', ROOT / 'ops/ci/agent_rules.py')
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)


class ValidatorUnitTests(unittest.TestCase):
    def metadata(self, name='example', description='Specific use case; not every task.'):
        return f'---\nname: {name}\ndescription: {json.dumps(description)}\n---\n\n# Example\n'

    def test_valid_skill(self):
        self.assertTrue(rules.skill_metadata(self.metadata(), 'example').lstrip().startswith('# Example'))

    def test_invalid_skill_metadata(self):
        invalid = [
            '# No metadata\n', '---\nname: example\n',
            '---\nname: example\n---\n# Example\n',
            self.metadata('different'),
            self.metadata().replace('description:', 'unknown:'),
            self.metadata().replace('name: example', 'name: example\nname: example'),
            self.metadata().replace('name: example', 'name: EXAMPLE'),
            self.metadata('example', ''), self.metadata('example', 'x' * 321),
            self.metadata('example', 'two\nlines'),
            self.metadata().replace('description: ', 'description: |\n'),
        ]
        for text in invalid:
            with self.subTest(text=text[:80]), self.assertRaises(ValueError):
                rules.skill_metadata(text, 'example')

    def test_links_and_fences(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'other.md').write_text('# Other\n')
            path = root / 'AGENTS.md'
            valid = '# Rules\n[local](other.md) [web](https://example.invalid/)\n```text\n[example](absent.md)\n```\n'
            rules.validate_markdown(valid, path, root)
            for text in ('# Rules\n[bad](absent.md)\n', '# Rules\n[bad](../escape.md)\n',
                         '# Rules\n[bad](/etc/passwd)\n', '# Rules\n```\n',
                         '# Rules\n~~~python\nx\n```\n', 'No heading\n'):
                with self.subTest(text=text), self.assertRaises(ValueError):
                    rules.validate_markdown(text, path, root)

    def test_symlink_escape_and_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            outside = Path(tmp) / 'external.md'
            outside.write_text('# External\n')
            link = root / 'AGENTS.md'
            link.symlink_to(outside)
            with self.assertRaises(ValueError):
                rules.read_document(link, root, 100)
            with self.assertRaises(ValueError):
                rules.validate_markdown('# Rules\n[bad](AGENTS.md)\n', root / 'x.md', root)
            with self.assertRaises(ValueError):
                rules.read_document(root / 'missing.md', root, 100)

    def test_invalid_document_size_encoding_and_ending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / 'AGENTS.md'
            for payload in (b'', b'x' * 101, b'# Rule', b'\xff\n', b'\xef\xbb\xbf# Rule\n', b'# Rule\x00\n', b'# Rule\r\n'):
                path.write_bytes(payload)
                with self.subTest(payload=repr(payload[:12])), self.assertRaises((ValueError, UnicodeError)):
                    rules.read_document(path, root, 100)

    def test_complete_synthetic_package_and_missing_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for relative in rules.RULE_PATHS:
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# Rules\n')
            for name in rules.SKILL_NAMES:
                path = root / f'.agents/skills/{name}/SKILL.md'
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(self.metadata(name))
            self.assertEqual(rules.check_repository(root), [])
            path.unlink()
            self.assertTrue(any('missing document' in error for error in rules.check_repository(root)))


    def synthetic_repository(self, root):
        for relative in rules.RULE_PATHS:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('# Rules\n')
        for name in rules.SKILL_NAMES:
            path = root / f'.agents/skills/{name}/SKILL.md'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(self.metadata(name))

    def test_unregistered_nested_agent_and_override_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.synthetic_repository(root)
            self.assertEqual(rules.check_repository(root), [])
            nested = root / 'backend/api/AGENTS.md'
            nested.parent.mkdir(parents=True, exist_ok=True)
            nested.write_text('# New rule\n')
            self.assertTrue(any('unregistered Agent rule: backend/api/AGENTS.md' in err
                                for err in rules.check_repository(root)))
            nested.unlink()
            override = root / 'frontend/AGENTS.override.md'
            override.write_text('# New override\n')
            self.assertTrue(any('unregistered Agent rule: frontend/AGENTS.override.md' in err
                                for err in rules.check_repository(root)))
            override.unlink()
            self.assertEqual(rules.check_repository(root), [])

    def test_unregistered_skill_directory_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.synthetic_repository(root)
            extra = root / '.agents/skills/newshub-database'
            extra.mkdir()
            self.assertTrue(any('unregistered project Skill: newshub-database' in err
                                for err in rules.check_repository(root)))
            (extra / 'SKILL.md').write_text(self.metadata('newshub-database'))
            self.assertTrue(any('unregistered project Skill: newshub-database' in err
                                for err in rules.check_repository(root)))
            (extra / 'SKILL.md').unlink()
            extra.rmdir()
            self.assertEqual(rules.check_repository(root), [])

    def test_root_worktrees_are_independent_but_business_rules_are_not_hidden(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.synthetic_repository(root)
            worktree = root / '.worktrees/task'
            worktree.mkdir(parents=True)
            self.synthetic_repository(worktree)
            extra = worktree / 'backend/api/AGENTS.md'
            extra.parent.mkdir(parents=True, exist_ok=True)
            extra.write_text('# Unregistered inside the other worktree\n')
            self.assertEqual(rules.check_repository(root), [])
            self.assertTrue(any('unregistered Agent rule: backend/api/AGENTS.md' in err
                                for err in rules.check_repository(worktree)))
            hidden = root / 'backend/.worktrees/AGENTS.md'
            hidden.parent.mkdir(parents=True)
            hidden.write_text('# Business directory is still checked\n')
            self.assertTrue(any('unregistered Agent rule: backend/.worktrees/AGENTS.md' in err
                                for err in rules.check_repository(root)))

    def test_generated_dependencies_do_not_create_false_positive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.synthetic_repository(root)
            third_party = root / 'frontend/node_modules/third_party/AGENTS.md'
            third_party.parent.mkdir(parents=True)
            third_party.write_text('# Third party\n')
            self.assertEqual(rules.check_repository(root), [])



class RepositoryAgentContractTests(unittest.TestCase):
    def test_actual_repository_rules_and_skills(self):
        self.assertEqual(rules.check_repository(ROOT), [])

    def test_build_release_policy_is_linked_and_has_valid_local_references(self):
        policy = ROOT / 'ops/ci/build-release-policy.md'
        rules.validate_markdown(policy.read_text(), policy, ROOT)
        for relative in ('AGENTS.md', 'ops/ci/AGENTS.md', 'scripts/deploy/AGENTS.md', 'tests/AGENTS.md'):
            with self.subTest(relative=relative):
                self.assertIn('build-release-policy.md', (ROOT / relative).read_text())
        self.assertIn('/.worktrees/', (ROOT / '.gitignore').read_text().splitlines())

    def test_frontend_and_backend_validation_entrypoints_exist(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        preflight = workflow.split('name: Fast cross-stack syntax preflight', 1)[1].split('      - name:', 1)[0]
        self.assertIn('python3 ops/ci/agent_rules.py', preflight)
        self.assertIn("-m unittest discover -s ops/ci/tests -p 'test_*.py'", workflow)

    def test_ci_router_does_not_treat_owned_agent_files_as_docs(self):
        router_spec = importlib.util.spec_from_file_location('newshub_change_scope', ROOT / 'ops/ci/change_scope.py')
        router = importlib.util.module_from_spec(router_spec)
        router_spec.loader.exec_module(router)
        paths = list(rules.RULE_PATHS) + [f'.agents/skills/{name}/SKILL.md' for name in rules.SKILL_NAMES]
        for path in paths:
            with self.subTest(path=path):
                self.assertNotEqual(router.route_paths([path]), (False, False))
        self.assertEqual(router.route_paths(['AGENTS.md']), (True, True))
        self.assertEqual(router.route_paths(['frontend/AGENTS.md']), (True, False))


if __name__ == '__main__':
    unittest.main()
