#!/usr/bin/env python3
"""Predogled popravkov imen AMOUR PARFUMS - → deklaracije_vendor."""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from services.fix_amour_parfums_names import preview_fix_amour_parfums_names

if __name__ == "__main__":
    shop = sys.argv[1] if len(sys.argv) > 1 else "amour-parfums-2.myshopify.com"
    app = create_app()
    with app.app_context():
        result = preview_fix_amour_parfums_names(shop)
        print(json.dumps(result, ensure_ascii=False, indent=2))
