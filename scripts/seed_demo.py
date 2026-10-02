"""Create or refresh the fictional demo database."""

from artwork_agent.config import load_config
from artwork_agent.db import open_database
from artwork_agent.seed import seed_demo


def main() -> None:
    config = load_config()
    db = open_database(config)
    seed_demo(db, config, force=True)
    print(f"Seeded demo data for {config.company_name}.")


if __name__ == "__main__":
    main()
