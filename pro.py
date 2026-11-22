#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google AI Pro 5TB & AI Ultra — $0 Free Trial One-Click Activation

Uses the same injection pipeline as ultra0.py:
    g1.2tb.ai.subs_variant  12months-eft / 6months-eft  (12-month / 6-month free trial)
    g1.play.2tb.ai          eft-3mo                     (3-month free trial)
    g1.play.20tb            Ultra 20TB (5x)
    g1.play.ai.pro          Ultra 30TB (20x)

Usage:
    python3 pro.py --check                                 # Environment self-check
    python3 pro.py --test-plans                            # Test/scan all Ultra & AI Pro offers
    python3 pro.py accounts.txt                            # Batch mode
    python3 pro.py --account "a@b.com:password:totp_key"   # Single account
    python3 pro.py --account "a@b.com:pass:totp" --plan ultra  # Activate Ultra tier

All other options match ultra0.py (--no-add / --no-switch / --serial / --plan / --offer).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ultra0  # noqa: E402


def main():
    if "--plan" not in sys.argv and "--test-plans" not in sys.argv:
        sys.argv += ["--plan", "pro"]
    ultra0.main()
    return 0


if __name__ == "__main__":
    sys.exit(main())
