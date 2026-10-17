"""`firstlight api|brain|edge`: one image, three processes."""

import argparse
import asyncio

from firstlight.core.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="firstlight")
    parser.add_argument("role", choices=["api", "brain", "edge"])
    parser.add_argument("--host", default="0.0.0.0")  # noqa: S104  (inside a container)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    configure_logging()

    if args.role == "api":
        import uvicorn

        uvicorn.run("firstlight.api.app:app", host=args.host, port=args.port, log_config=None)
    elif args.role == "brain":
        from firstlight.brain.main import run

        asyncio.run(run())
    else:
        from firstlight.edge.main import run as run_edge

        asyncio.run(run_edge())


if __name__ == "__main__":
    main()
