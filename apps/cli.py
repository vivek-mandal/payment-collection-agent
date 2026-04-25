"""Interactive CLI for the payment-collection agent.

Usage::

    python -m apps.cli
    payment-agent           # if installed via `pip install -e .`

Reads configuration from environment variables (or a ``.env`` file via
pydantic-settings). Required variables are listed in ``.env.example``.
"""

from __future__ import annotations

import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from pydantic import ValidationError

from payment_agent import Agent, State
from payment_agent.config import get_settings


def _print_banner() -> None:
    print("\n" + "=" * 60)
    print("  💳  Payment Collection Agent  (type 'quit' to exit)")
    print("=" * 60 + "\n")


def _check_settings() -> None:
    try:
        get_settings()
    except ValidationError as exc:
        print("❌  Configuration error:\n")
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            print(f"  {loc}: {err['msg']}")
        print("\nSet the required variables in a .env file (see .env.example).")
        sys.exit(1)


def main() -> None:
    _check_settings()
    _print_banner()

    agent = Agent()

    opening = agent.next("Hello")
    print(f"Agent: {opening['message']}\n")

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nSession ended.")
            break

        if not user_input:
            continue

        if user_input.lower() in ("quit", "exit", "q"):
            print("\nGoodbye!")
            break

        response = agent.next(user_input)
        print(f"\nAgent: {response['message']}\n")

        if agent.state in (State.DONE, State.FAILED):
            print("─" * 60)
            print("Session complete. Restart to begin a new conversation.")
            break


if __name__ == "__main__":
    main()
