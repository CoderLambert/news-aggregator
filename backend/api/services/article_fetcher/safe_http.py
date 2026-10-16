"""Compatibility import for shared HTTP safety; contains no extraction logic."""
import sys
from api.services import safe_http as _module
sys.modules[__name__] = _module
