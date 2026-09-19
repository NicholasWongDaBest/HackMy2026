"""Compatibility entry point; Task2 sync uses the maintained farm code.

Run ONE worker: python3 -m farm.sync (preferred) or python3 -m app.sync.
The shared farm.config is authoritative for both commands.
"""
from farm.sync import main, pull_batch, push_batch


if __name__ == "__main__":
    raise SystemExit(main())
