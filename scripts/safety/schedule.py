"""Inspect city cadence without installing the retired daily LaunchAgent."""
import argparse

from cadence import main as inspect_plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['show', 'install', 'remove'])
    parser.add_argument('--state')
    parser.add_argument('--now')
    args = parser.parse_args()
    if args.action != 'show':
        parser.error('Legacy OS timer management is retired; the owner uses a separate Codex coordination heartbeat. '
                     'This command does not install, replace or remove any LaunchAgent.')
    arguments = []
    for name in ('state', 'now'):
        value = getattr(args, name)
        if value is not None:
            arguments.extend(['--' + name, value])
    inspect_plan(arguments)


if __name__ == '__main__':
    main()
