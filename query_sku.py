#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""query_sku.py — Query all subscription offers for one or more specific SKUs.

Usage:
    python query_sku.py g1.2tb.ai.subs_variant [other_sku...]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ultra0  # noqa: E402


def main():
    skus = sys.argv[1:] or ["g1.2tb.ai.subs_variant"]
    ultra0.ADB = ultra0.find_adb()
    ultra0.pick_device()
    ultra0.ensure_root()
    ultra0.ensure_network()
    ultra0.ensure_frida_server()
    ultra0.ensure_module_apk()
    ultra0.ensure_vending()
    for sku in skus:
        ultra0.test_all_plans(sku=sku, plan="all")
    return 0


if __name__ == "__main__":
    sys.exit(main())
