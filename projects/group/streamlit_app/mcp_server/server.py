"""MCP server for scam signal lookups backed by the local scam CSV."""

from __future__ import annotations

import argparse
import logging
from functools import lru_cache

import uvicorn
from mcp.server.fastmcp import FastMCP
from starlette.middleware.cors import CORSMiddleware

from guardian.data.scam_db import ScamDatabase
from guardian.data.scam_signals import ScamDbProvider
from guardian.paths import SCAM_DB_CSV

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger(__name__)

mcp = FastMCP(
    "Guardian Scam Signal MCP",
    instructions=(
        "Local CSV-backed MCP server for scam signal checks. "
        "Use tools to lookup caller numbers, detect phishing domains, "
        "and scan messages for scam keywords."
    ),
    json_response=True,
)


@lru_cache(maxsize=1)
def provider() -> ScamDbProvider:
    db = ScamDatabase.from_csv(SCAM_DB_CSV.read_text(encoding="utf-8"))
    log.info("Scam signal provider loaded from %s", SCAM_DB_CSV)
    return ScamDbProvider(db)


@mcp.tool()
def lookup_number(number: str) -> dict:
    """Check whether a caller number matches scam blocklist entries."""
    out = provider().lookup_number(number)
    out["source"] = "mcp"
    out.pop("fallback", None)
    return out


@mcp.tool()
def check_domain(text: str) -> dict:
    """Check text for phishing/scam domains from the local database."""
    out = provider().check_domain(text)
    out["source"] = "mcp"
    out.pop("fallback", None)
    return out


@mcp.tool()
def search_keywords(text: str) -> dict:
    """Search text for known scam keywords and return weighted matches."""
    out = provider().search_keywords(text)
    out["source"] = "mcp"
    out.pop("fallback", None)
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Guardian scam-signal MCP server.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for the scam-signal MCP HTTP server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Bind port for the scam-signal MCP HTTP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="MCP transport to run for the scam-signal server.",
    )
    args = parser.parse_args()

    mcp.settings.host = args.host
    mcp.settings.port = args.port
    provider()

    if args.transport == "streamable-http":
        app = CORSMiddleware(
            mcp.streamable_http_app(),
            allow_origins=["*"],
            allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
            allow_headers=["*"],
            expose_headers=["Mcp-Session-Id"],
        )
        uvicorn.run(app, host=args.host, port=args.port)
        return

    mcp.run()


if __name__ == "__main__":
    main()
