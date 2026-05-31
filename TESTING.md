# News Aggregator Testing Guide

## Overview

This project uses a comprehensive testing strategy to catch bugs before they reach production.

## Test Structure

```
tests/
├── backend/
│   ├── test_content_cleaner.py    # GitHub content cleaning tests
│   ├── test_llm_translator.py     # Translation service tests
│   └── test_api_views.py          # API endpoint tests
├── crawler/
│   └── test_spiders.py            # Spider parsing tests
└── conftest.py                    # Shared test configuration
```

## Running Tests

### All tests
```bash
cd /root/news-aggregator
./scripts/run_tests.sh
```

### Backend tests only
```bash
cd /root/news-aggregator/backend
python -m pytest ../tests/backend/ -v
```

### Specific test file
```bash
cd /root/news-aggregator/backend
python -m pytest ../tests/backend/test_content_cleaner.py -v
```

### Specific test class
```bash
cd /root/news-aggregator/backend
python -m pytest ../tests/backend/test_content_cleaner.py::TestCleanGithubContent -v
```

### Specific test method
```bash
cd /root/news-aggregator/backend
python -m pytest ../tests/backend/test_content_cleaner.py::TestCleanGithubContent::test_removes_footer -v
```

## Build Validation

The `scripts/validate_build.py` script runs after each frontend build to catch common issues:

```bash
cd /root/news-aggregator
python scripts/validate_build.py
```

Checks performed:
- Dist directory exists
- JS imports are valid
- CSS files exist
- Bundle size is reasonable

## Test-Driven Development (TDD) Workflow

When implementing new features:

1. **Write a failing test first** (RED)
   ```python
   def test_new_feature_behavior():
       # Test what the feature should do
       assert feature() == expected_result
   ```

2. **Run the test to verify it fails**
   ```bash
   python -m pytest tests/backend/test_new_feature.py::test_new_feature_behavior -v
   ```

3. **Write minimal code to pass** (GREEN)
   ```python
   def feature():
       return expected_result
   ```

4. **Run the test to verify it passes**
   ```bash
   python -m pytest tests/backend/test_new_feature.py::test_new_feature_behavior -v
   ```

5. **Refactor** (keep tests green)

## Key Testing Principles

1. **Test behavior, not implementation** - Tests should verify what the code does, not how it does it
2. **One assertion per test** - Each test should verify one specific behavior
3. **Test edge cases** - Empty inputs, None values, error conditions
4. **No mocks unless necessary** - Test real code whenever possible
5. **Tests must be deterministic** - Same input always produces same output

## Adding New Tests

When adding a new feature or fixing a bug:

1. Create a test file in `tests/backend/` or `tests/crawler/`
2. Follow the naming convention: `test_<module_name>.py`
3. Use descriptive test names: `test_<behavior_under_test>`
4. Include both happy path and edge case tests

Example:
```python
class TestNewFeature:
    def test_happy_path(self):
        # Normal case
        pass
    
    def test_empty_input(self):
        # Edge case
        pass
    
    def test_error_handling(self):
        # Error case
        pass
```

## CI/CD Integration

Tests should run:
- Before each commit (pre-commit hook)
- After each frontend build
- Before deployment

The `run_tests.sh` script can be integrated into cron jobs or CI pipelines.
