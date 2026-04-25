"""
cli.py — Interactive CLI for the payment collection agent.

Usage:
    python cli.py

Set environment variables before running:
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_DEPLOYMENT_NAME
"""

import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv optional — env vars can be set directly


def check_env():
    required = ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT_NAME"]
    missing = [v for v in required if not os.environ.get(v)]
    if missing:
        print("❌  Missing required environment variables:")
        for v in missing:
            print(f"    {v}")
        print("\nSet them in a .env file or export them before running.")
        sys.exit(1)


def print_banner():
    print("\n" + "=" * 60)
    print("  💳  Payment Collection Agent  (type 'quit' to exit)")
    print("=" * 60 + "\n")


def main():
    check_env()

    from agent import Agent

    print_banner()
    agent = Agent()

    # Kick off the conversation automatically
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

        # Session closed naturally
        from agent import State
        if agent.state in (State.DONE, State.FAILED):
            print("─" * 60)
            print("Session complete. Restart to begin a new conversation.")
            break


if __name__ == "__main__":
    main()
