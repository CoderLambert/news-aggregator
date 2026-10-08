from pathlib import Path


def test_dockerignore_excludes_data_and_common_credentials():
    project = Path(__file__).resolve().parents[2]
    patterns = {
        line.strip()
        for line in (project / '.dockerignore').read_text(encoding='utf-8').splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    }

    assert {'.env', '.env.*', '**/*.sqlite3', '**/*.sqlite3-wal', '**/*.sqlite3-shm'} <= patterns
    assert {'*.pem', '*.key', '*.p12', '*.pfx', '*.crt', '*.cer'} <= patterns
