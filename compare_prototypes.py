"""Compare deterministic retrieval with the ReAct prototype.

The script intentionally keeps the comparison small and transparent: both
prototypes receive the same question, while the second one may perform
multiple tool calls.
"""

import argparse

from src.agent.react_agent import ReActAgent
from src.agent.tools import AgentTools


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", default="Wie hoch ist der Arbeitspreis?")
    parser.add_argument("--agent", action="store_true", help="Zusätzlich den ReAct-Agenten ausführen.")
    args = parser.parse_args()

    tools = AgentTools()
    print("=== Prototyp 1: deterministische Tabellen-Suche ===")
    print(tools.search_tables(args.question, top_k=5))

    if args.agent:
        print("\n=== Prototyp 2: Agentic RAG ===")
        print(ReActAgent().run(args.question))


if __name__ == "__main__":
    main()