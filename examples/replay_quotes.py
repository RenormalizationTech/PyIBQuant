"""Validate and summarize quote recordings from disk without TWS or optional dependencies."""

import argparse
import json
from pathlib import Path

from pyibquant import QuoteRecording, QuoteRecordingSet


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    parser.add_argument('--recording-set', action='store_true', help='Read a rotation manifest')
    parser.add_argument('--allow-incomplete', action='store_true', help='Inspect a partial session')
    args = parser.parse_args()
    opener = QuoteRecordingSet.open if args.recording_set else QuoteRecording.open
    try:
        with opener(args.path, allow_incomplete=args.allow_incomplete) as recording:
            print(json.dumps(dict(metadata=recording.metadata(), quality=recording.quality(),
                                  fingerprint=recording.fingerprint()), indent=2))
    except (ValueError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
