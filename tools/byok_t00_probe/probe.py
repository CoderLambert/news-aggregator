"""Run T00 SDK_LOCAL checks against an in-process loopback HTTP upstream."""

from __future__ import annotations

import argparse
import sys
import unittest

from .test_probe import SDKProtocolProbeTests


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("sdk-local",),
        default="sdk-local",
        help="SDK_LOCAL is the only mode this probe runs; real provider calls are separate.",
    )
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SDKProtocolProbeTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.wasSuccessful():
        print("SDK_LOCAL=PASS providers_called=0 upstream=loopback")
        return 0
    print("SDK_LOCAL=FAIL providers_called=0 upstream=loopback")
    return 1


if __name__ == "__main__":
    sys.exit(main())
