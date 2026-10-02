"""Inspect cadence; the legacy collect-and-build entrypoint is retired."""
import argparse

from cadence import main as inspect_plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', action='store_true', help='Read-only cadence inspection')
    parser.add_argument('--state')
    parser.add_argument('--now')
    args = parser.parse_args()
    if not args.plan:
        parser.error('Direct collection/build is retired. See docs/UPDATES.md for the checked update process.')
    arguments = []
    for name in ('state', 'now'):
        value = getattr(args, name)
        if value is not None:
            arguments.extend(['--' + name, value])
    inspect_plan(arguments)


if __name__ == '__main__':
    main()
