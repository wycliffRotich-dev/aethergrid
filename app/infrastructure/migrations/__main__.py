"""Apply the migrations: python -m app.infrastructure.migrations (ADR 0071)."""

from app.infrastructure.migrations.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
