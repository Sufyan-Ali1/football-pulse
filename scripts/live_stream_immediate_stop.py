from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from publish.livestream import delete_broadcast, get_broadcast, transition_broadcast
from livestream.stream_encoder import stop_encoder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("live_stream_immediate_stop")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stop an immediate livestream test cleanly.")
    parser.add_argument("--broadcast-id", required=True, help="Broadcast ID to stop/delete.")
    parser.add_argument(
        "--delete-if-not-live",
        action="store_true",
        help="Delete the broadcast if it never reached a live state instead of trying to complete it.",
    )
    args = parser.parse_args()

    details = get_broadcast(args.broadcast_id)
    logger.info("Current broadcast state: %s", details.life_cycle_status)

    if details.life_cycle_status in {"live", "testing"}:
        transition_broadcast(args.broadcast_id, "complete")
        logger.info("Broadcast transitioned to complete: %s", args.broadcast_id)
    elif details.life_cycle_status == "complete":
        logger.info("Broadcast already complete: %s", args.broadcast_id)
    elif args.delete_if_not_live:
        delete_broadcast(args.broadcast_id)
        logger.info("Broadcast deleted: %s", args.broadcast_id)
    else:
        logger.warning(
            "Broadcast is in state '%s'. Use --delete-if-not-live if you want to delete it.",
            details.life_cycle_status,
        )

    stop_encoder()
    logger.info("Encoder stopped.")


if __name__ == "__main__":
    main()
