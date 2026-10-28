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

    def test_workflow_skills_allow_direct_execution_without_mandatory_delegate(self):
        root_rules = (ROOT / 'AGENTS.md').read_text()
        validation = root_rules.split('## Validation and delivery', 1)[1]
        self.assertIn('agents may execute directly', validation)
        self.assertIn('agent count are task choices', validation)
        self.assertIn('project-local Skills take precedence', validation)
        for name in ('newshub-test-acceptance', 'newshub-stage-commit', 'newshub-release-delivery'):
            relative = f'.agents/skills/{name}/SKILL.md'
            with self.subTest(skill=name):
                self.assertIn(name, rules.SKILL_NAMES)
                self.assertIn(relative, root_rules)
                text = (ROOT / relative).read_text()
                self.assertIn('current agent may', text)
                self.assertNotRegex(text + validation,
                                    r'(?i)must spawn|exactly one|one pinned|If Luna|BLOCKED without fallback')

    def test_execution_choice_preserves_authorization_and_safety_contracts(self):
        root_rules = (ROOT / 'AGENTS.md').read_text()
        for guard in ('Local-first acceptance', 'Unknown authorization fails closed',
                      'credential_epoch', 'A closed connection/EOF is not successful SSE completion',
                      'Failed checks stop delivery', 'merge-gate', 'SKIPPED/NOT_RUN/BLOCKED'):
            with self.subTest(guard=guard):
                self.assertIn(guard, root_rules)
        acceptance = (ROOT / '.agents/skills/newshub-test-acceptance/SKILL.md').read_text()
        self.assertIn('Do not read real `.env` files', acceptance)
        self.assertIn('Do not weaken tests', acceptance)
        commit = (ROOT / '.agents/skills/newshub-stage-commit/SKILL.md').read_text()
        self.assertIn('no-push/local-only blocks only the push', commit)
        self.assertIn('A required failure stops before commit', commit)
        self.assertIn('Never reset, clean, stash, amend, rebase, merge or force-push', commit)
        release = (ROOT / '.agents/skills/newshub-release-delivery/SKILL.md').read_text()
        for guard in ('Production deployment', 'expected-head-guarded', 'skipped/missing is not PASS',
                      'No reset/stash/autostash', 'Return to local acceptance for new fixes'):
            with self.subTest(guard=guard):
                self.assertIn(guard, release)
        # Local image builds retain their separate, explicitly authorized tool contract.
        self.assertIn('docs/development/pi-local-image-builder.md', root_rules)
        policy = (ROOT / 'docs/development/pi-local-image-builder.md').read_text()
        self.assertIn('openai-codex/gpt-6-luna', policy)
        self.assertIn('explicit', policy.lower())

    def test_project_release_skill_cannot_bypass_structure_validation(self):
        name = 'newshub-release-delivery'
        self.assertIn(name, rules.SKILL_NAMES)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ValidatorUnitTests().synthetic_repository(root)
            path = root / f'.agents/skills/{name}/SKILL.md'
            valid = path.read_text()
            for invalid in (valid.replace(f'name: {name}', 'name: different'),
                            valid + '[escape](../../../../outside.md)\n'):
                with self.subTest(invalid=invalid):
                    path.write_text(invalid)
                    self.assertTrue(any(f'.agents/skills/{name}/SKILL.md:' in error
                                        for error in rules.check_repository(root)))
            path.unlink()
            self.assertTrue(any(f'.agents/skills/{name}/SKILL.md: missing document' in error
                                for error in rules.check_repository(root)))

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
