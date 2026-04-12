"""
Einzel-Lauf-Wrapper für GitHub Actions.
Führt genau einen Check-Zyklus durch (kein Loop).
"""
import asyncio
import os

# Dotenv nur lokal laden
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Patch: Loop deaktivieren
import monitor
monitor.CHECK_INTERVAL_MINUTES = 0


async def main():
    saved_states = monitor.load_state()
    await monitor.run_checks(saved_states)
    monitor.save_state(saved_states)


if __name__ == "__main__":
    asyncio.run(main())
