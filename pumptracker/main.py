"""Orchestrator: check every target, diff against saved state, alert on new stock.

Run modes:
    python -m pumptracker.main                 # one check pass (what Actions runs)
    python -m pumptracker.main --dry-run       # check + print, never send/save
    python -m pumptracker.main --test-notify   # send a test alert and exit
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Optional

import yaml

from . import notify
from .models import ProductResult
from .scrapers import base
from .scrapers.generic import check_target

log = logging.getLogger("pumptracker")

_PKG_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = _PKG_DIR / "config.yaml"
DEFAULT_STATE = _PKG_DIR / "state.json"


def load_config(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not read state file (%s); starting fresh.", exc)
        return {}


def save_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=2, sort_keys=True)
        fh.write("\n")
    tmp.replace(path)


def _is_new_stock(result: ProductResult, prev: Optional[dict]) -> bool:
    """Alert only when a check succeeds AND stock flips from not-in-stock to in-stock."""
    if not result.ok or result.in_stock is not True:
        return False
    prev_in_stock = prev.get("in_stock") if prev else None
    return prev_in_stock is not True


def _merge_state(result: ProductResult, prev: Optional[dict], alerted: bool) -> dict:
    """Build the new state entry, carrying forward known stock across error blips."""
    prev = prev or {}
    # On a failed/unknown check, keep the last known in_stock so a later recovery
    # doesn't look like a fresh transition and double-alert.
    in_stock = result.in_stock if result.ok else prev.get("in_stock")
    entry = {
        "vendor": result.vendor,
        "product": result.product,
        "url": result.url,
        "in_stock": in_stock,
        "price": result.price if result.ok else prev.get("price"),
        "price_text": result.price_text if result.ok else prev.get("price_text"),
        "last_checked": result.checked_at,
        "last_error": result.error,
        "last_in_stock_at": prev.get("last_in_stock_at"),
        "last_alerted_at": prev.get("last_alerted_at"),
    }
    if result.in_stock is True:
        entry["last_in_stock_at"] = result.checked_at
    if alerted:
        entry["last_alerted_at"] = result.checked_at
    return entry


def _print_summary(results: list[ProductResult]) -> None:
    print("\n=== Pool pump tracker — results ===")
    width = max((len(r.vendor) for r in results), default=6)
    for r in results:
        line = f"{r.vendor:<{width}}  {r.status_display():<12}  {r.price_display():>9}  {r.product}"
        print(line)
        if r.error:
            print(f"{'':<{width}}  └─ {r.error}")
    print("===================================\n")


def run_once(config: dict, state_path: Path, *, dry_run: bool) -> list[ProductResult]:
    settings = config.get("settings", {})
    targets = config.get("targets", [])
    state = load_state(state_path)
    debug = bool(os.environ.get("PUMPTRACKER_DEBUG"))

    results: list[ProductResult] = []
    lo = settings.get("min_delay_seconds", 2)
    hi = settings.get("max_delay_seconds", 6)

    with base.Fetcher(settings) as fetcher:
        for i, target in enumerate(targets):
            if i > 0:
                time.sleep(random.uniform(lo, hi))  # polite pacing between vendors
            log.info("Checking %s — %s", target["vendor"], target["product"])
            result = check_target(target, settings, fetcher, debug=debug)
            log.info("  -> %s  %s", result.status_display(), result.price_display())
            if result.debug:
                log.info("  debug: %s", result.debug)
            results.append(result)

    # Diff, collect alerts, build next state.
    new_stock: list[ProductResult] = []
    new_state = dict(state)
    for r in results:
        prev = state.get(r.target_id)
        alerted = _is_new_stock(r, prev)
        if alerted:
            new_stock.append(r)
        new_state[r.target_id] = _merge_state(r, prev, alerted)

    _print_summary(results)

    if new_stock:
        log.info("%d newly in-stock listing(s) — sending alert.", len(new_stock))
        subject, body = notify.format_alert(new_stock)
        notify.notify(subject, body, dry_run=dry_run)
    else:
        log.info("No new in-stock transitions this run.")

    if dry_run:
        log.info("[dry-run] state not written.")
    else:
        save_state(state_path, new_state)
        log.info("State saved to %s", state_path)

    return results


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="UK pool pump availability tracker")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--once", action="store_true",
                        help="Run a single pass (default; scheduling is handled by cron).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Check and print, but never send alerts or write state.")
    parser.add_argument("--test-notify", action="store_true",
                        help="Send a test alert on every configured channel, then exit.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    if args.test_notify:
        notify.test_notify()
        return 0

    config = load_config(args.config)
    results = run_once(config, args.state, dry_run=args.dry_run)

    # Exit non-zero only if every target errored (signals a real problem in CI),
    # not merely because things are out of stock.
    if results and all(r.error is not None for r in results):
        log.error("All targets errored this run.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
