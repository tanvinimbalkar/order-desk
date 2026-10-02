"""Remove every stored row for a trial company. Requires --yes."""

from __future__ import annotations

import argparse

from artwork_agent.config import load_config
from artwork_agent.db import open_database, wipe


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Delete all stored data for this trial company.")
    parser.add_argument("--yes", action="store_true", help="Confirm the delete.")
    args = parser.parse_args(argv)
    if not args.yes:
        raise SystemExit("Refusing to delete. Run again with --yes when the trial is over.")
    config = load_config()
    db = open_database(config)
    wipe(db)
    print(f"Deleted stored data for {config.company_name}.")


if __name__ == "__main__":
    main()
