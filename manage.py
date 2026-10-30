#!/usr/bin/env python
"""Command-line utility for administrative tasks of the CivicSense platform."""
import os
import sys


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "civicsense.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "Django is not installed. Run 'pip install -r requirements.txt' first."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
