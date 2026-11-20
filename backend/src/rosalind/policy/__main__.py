"""Run the policy service with uvicorn."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("ROSALIND_POLICY_HOST", "127.0.0.1")
    port = int(os.environ.get("ROSALIND_POLICY_PORT", "8001"))
    uvicorn.run(
        "rosalind.policy.api.app:app",
        host=host,
        port=port,
    )


if __name__ == "__main__":
    main()
