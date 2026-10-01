"""Save the morning brief and the three suggested answers for each sample day.

The app calls Gemini when it can. These files are the fallback. Run this from
the project root after GEMINI_API_KEY and MODEL are set in .streamlit/secrets.toml.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.brief import BriefError, build_facts, generate_gemini_brief, rule_based_brief, write_day_cache  # noqa: E402
from core.chat import build_chip_cache  # noqa: E402
from core.match import match_orders  # noqa: E402
from data.sample import SAMPLE_DAYS, build_inbound, build_sample  # noqa: E402


def _match(day: dict):
    packets = build_sample(day["seed"], day=day["id"])
    return match_orders(
        [packet.purchase_order for packet in packets],
        [packet.shipment for packet in packets],
        [packet.invoice for packet in packets],
        build_inbound(day["id"]),
    )


def main() -> int:
    logging.basicConfig(level=logging.WARNING)
    for day in SAMPLE_DAYS:
        results = _match(day)
        chips = build_chip_cache(results)
        try:
            text, _model = generate_gemini_brief(results)
            source = "gemini"
        except BriefError as exc:
            logging.warning("%s", exc)
            text = rule_based_brief(build_facts(results))
            source = "rules"
        except Exception as exc:
            logging.warning("Brief fallback for %s: %s", day["label"], exc.__class__.__name__)
            text = rule_based_brief(build_facts(results))
            source = "rules"
        write_day_cache(day["id"], text, chips, source)
        print(f"{day['label']}: saved a {len(text.splitlines())}-line brief and 3 answers ({source})")
    print("Saved fallbacks to data/cache/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
