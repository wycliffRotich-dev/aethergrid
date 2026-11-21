"""
Entry point of the public app (ADR 0102, decision 6).

Run it with: uvicorn app.public_main:create_app --factory
Importing this module opens nothing.
"""

from app.presentation.public.composition import create_app

__all__ = ["create_app"]
