"""Deprecated compatibility shim.

Use src.app.web.run instead.
"""

from src.app.web.run import main

__all__ = ["main"]


if __name__ == "__main__":
    main()
