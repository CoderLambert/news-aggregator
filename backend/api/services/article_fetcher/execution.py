"""Compatibility import for shared HTTP safety; contains no extraction logic."""
import sys
from api.services import http_execution as _module
sys.modules[__name__] = _module
