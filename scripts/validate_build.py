"""
Build validation script for the news aggregator frontend.
Runs after `npm run build` to catch common issues before deployment.
"""
import json
import os
import re
import sys


def check_dist_exists():
    """Check that the dist directory exists and has required files."""
    dist_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
    if not os.path.isdir(dist_dir):
        print("ERROR: dist/ directory not found. Run `npm run build` first.")
        return False
    
    index_html = os.path.join(dist_dir, 'index.html')
    if not os.path.isfile(index_html):
        print("ERROR: dist/index.html not found.")
        return False
    
    return True


def check_js_imports():
    """Check that the main JS file has valid imports."""
    dist_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
    assets_dir = os.path.join(dist_dir, 'assets')
    
    if not os.path.isdir(assets_dir):
        print("ERROR: dist/assets/ directory not found.")
        return False
    
    # Find the main index JS file
    js_files = [f for f in os.listdir(assets_dir) if f.startswith('index-') and f.endswith('.js')]
    if not js_files:
        print("ERROR: No index-*.js file found in dist/assets/.")
        return False
    
    main_js = os.path.join(assets_dir, js_files[0])
    with open(main_js, 'r', encoding='utf-8') as f:
        content = f.read()
    
    errors = []
    
    # Check for common React import issues
    if 'useState' in content and 'useRef' in content:
        # Both are used, check if useRef is properly imported
        if 'useRef' in content and 'e.useRef' not in content and 'r.useRef' not in content:
            # Check if it's in the React exports
            if 'useState' in content[:500] and 'useRef' not in content[:500]:
                errors.append("WARNING: useRef is used but may not be properly imported from React")
    
    # Check for undefined references (common minification issue)
    undefined_patterns = [
        r'\bundefinedshell\b',
        r'\bundefined\n',
    ]
    for pattern in undefined_patterns:
        matches = re.findall(pattern, content)
        if matches:
            errors.append(f"WARNING: Found pattern '{pattern}' in JS bundle - may indicate content issues")
    
    if errors:
        for err in errors:
            print(err)
        return False
    
    return True


def check_css_exists():
    """Check that CSS files exist."""
    dist_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
    assets_dir = os.path.join(dist_dir, 'assets')
    
    css_files = [f for f in os.listdir(assets_dir) if f.endswith('.css')]
    if not css_files:
        print("WARNING: No CSS files found in dist/assets/.")
        return False
    
    return True


def check_bundle_size():
    """Check that bundle sizes are reasonable."""
    dist_dir = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
    assets_dir = os.path.join(dist_dir, 'assets')
    
    js_files = [f for f in os.listdir(assets_dir) if f.endswith('.js')]
    total_js_size = 0
    
    for f in js_files:
        size = os.path.getsize(os.path.join(assets_dir, f))
        total_js_size += size
        if size > 5 * 1024 * 1024:  # 5MB warning
            print(f"WARNING: {f} is {size / 1024 / 1024:.1f}MB - consider code splitting")
    
    if total_js_size > 10 * 1024 * 1024:  # 10MB total warning
        print(f"WARNING: Total JS bundle size is {total_js_size / 1024 / 1024:.1f}MB")
        return False
    
    return True


def main():
    print("=" * 50)
    print("Frontend Build Validation")
    print("=" * 50)
    
    checks = [
        ("Dist directory", check_dist_exists),
        ("JS imports", check_js_imports),
        ("CSS files", check_css_exists),
        ("Bundle size", check_bundle_size),
    ]
    
    all_passed = True
    for name, check_fn in checks:
        print(f"\nChecking {name}...")
        if not check_fn():
            all_passed = False
            print(f"  FAILED: {name}")
        else:
            print(f"  OK: {name}")
    
    print()
    if all_passed:
        print("All checks passed!")
        return 0
    else:
        print("Some checks failed!")
        return 1


if __name__ == '__main__':
    sys.exit(main())
