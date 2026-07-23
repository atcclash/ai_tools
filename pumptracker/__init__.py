"""UK pool pump availability tracker.

Watches UK retailers for the Intex SX925 (and compatible pumps for a 10ft Bestway
Steel Pro Max) and alerts via Telegram (primary) + Gmail email (fallback) when a
watched pump transitions into stock. Designed to run unattended on GitHub Actions.
"""

__version__ = "0.1.0"
