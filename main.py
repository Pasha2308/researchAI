"""CLI Entrypoint wrapper for backwards compatibility.

Redirects directly to cli.py in the modernized evidence-first research architecture.
"""

from cli import main

if __name__ == "__main__":
    main()
