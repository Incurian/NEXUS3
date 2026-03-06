"""Carriage-return rendering probe for manual multi-emulator verification."""

import sys


def main() -> None:
    # Intentional carriage return payload used in post-M4 terminal follow-up.
    sys.stdout.write("prompt-safe\rprompt-overwrite\n")


if __name__ == "__main__":
    main()
