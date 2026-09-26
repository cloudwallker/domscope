"""Command-line interface: python -m domscope audit ..."""
import argparse
from pathlib import Path
import sys

from . import __version__
from .audit import AuditError, audit_manifest
from .manifest import ManifestError
from .report import ReportError, write_report


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Offline HTML representation auditing; no model or network access.")
    parser.add_argument("--version", action="version", version=f"DOMScope {__version__}")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit", help="Audit local HTML pages and write a new report bundle")
    audit.add_argument("--manifest", required=True, type=Path)
    audit.add_argument("--out", required=True, type=Path)
    audit.add_argument("--max-bytes", type=positive_int, default=2097152)
    audit.add_argument("--max-samples", type=positive_int, default=5000)
    audit.add_argument("--max-nodes", type=positive_int, default=50000)
    args = parser.parse_args(argv)
    try:
        result = audit_manifest(args.manifest, max_bytes=args.max_bytes,
                                max_samples=args.max_samples, max_nodes=args.max_nodes)
        write_report(result, args.out)
    except (AuditError, ManifestError, ReportError) as exc:
        print(f"DOMScope: {exc}", file=sys.stderr)
        return 2
    except OSError:
        print("DOMScope: input or output could not be accessed; check paths and permissions.", file=sys.stderr)
        return 2
    counts = result.summary["counts"]
    print(f"DOMScope: {counts['valid']} valid / {counts['input']} input; {counts['excluded']} excluded.")
    print(f"Report written. Data kind: {result.summary['data_kind']}. Open summary.json in the viewer.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
