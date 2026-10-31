"""PyInstaller entry; application startup still goes through the regular CLI."""

from buddy.main import main

raise SystemExit(main())
