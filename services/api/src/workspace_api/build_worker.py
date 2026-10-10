"""Build worker: claims queued builds and runs them in the isolated runner (ADR-0015).

Run it as its own process on a host with a container runtime and the runner image, never
inside the API process:

    uv run python -m workspace_api.build_worker            # poll every 2 s
    uv run python -m workspace_api.build_worker --once     # process at most one build

The worker needs database access and Docker; it needs no model credentials.
"""

from __future__ import annotations

import argparse
import logging
import os
import time

from build_runner import SandboxLimits

from . import builds
from .config import Settings
from .db import Database

log = logging.getLogger("workspace_api.build_worker")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build-worker", description=__doc__)
    parser.add_argument("--once", action="store_true", help="process at most one queued build, then exit")
    parser.add_argument("--poll", type=float, default=2.0, help="seconds between polls when idle")
    parser.add_argument("--image", default=os.environ.get("BUILD_RUNNER_IMAGE", "workspace-build-runner:local"))
    parser.add_argument("--timeout", type=float, default=300.0, help="per-build wall-clock limit in seconds")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    db = Database(Settings.from_env().database_url)
    limits = SandboxLimits(timeout_s=args.timeout)
    try:
        while True:
            build_id = builds.process_one(db, args.image, limits)
            if build_id is not None:
                log.info("finished build %s", build_id)
            if args.once:
                return 0
            if build_id is None:
                time.sleep(args.poll)
    except KeyboardInterrupt:
        return 0
    finally:
        db.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
