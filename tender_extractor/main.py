"""
main.py — CLI entry point for the Tender Extractor system.

Usage:
  python main.py --input ./tender_docs --output ./output --format json --verbose

Flags:
  --input   : path to a .zip file, folder, or single PDF/DOCX/XLSX
  --output  : output folder (default: ./output)
  --format  : json | csv | both  (default: json)
  --verbose : show per-field extraction detail in the terminal
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _setup_logging(verbose: bool) -> None:
    """Configure root logger — INFO normally, DEBUG in verbose mode."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%H:%M:%S",
        level=level,
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def _parse_args() -> argparse.Namespace:
    """Define and parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Tender Document Extractor — fully offline, rule-based, no LLM.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        help="Path to a .zip file, folder, or single PDF / DOCX / XLSX file.",
    )
    parser.add_argument(
        "--output", "-o",
        default="./output",
        help="Directory where result files will be written.",
    )
    parser.add_argument(
        "--format", "-f",
        choices=["json", "csv", "both"],
        default="json",
        help="Output format: json, csv, or both.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        default=False,
        help="Print per-field extraction details in the terminal.",
    )
    return parser.parse_args()


def main() -> None:
    """Parse arguments and run the extraction pipeline."""
    args = _parse_args()
    _setup_logging(args.verbose)

    log = logging.getLogger("main")

    input_path = Path(args.input)
    if not input_path.exists():
        log.error(f"Input path does not exist: {input_path}")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    file_format = "both" if args.format == "both" else args.format

    log.info(f"Starting extraction | input={input_path} | output={output_dir} | format={file_format}")

    # Import pipeline here so module-level errors surface cleanly
    from tender_extractor.pipeline import process_batch

    results = process_batch(
        input_path=str(input_path),
        output_dir=str(output_dir),
        file_format=file_format,
        verbose=args.verbose,
    )

    ok  = sum(1 for r in results if not r.get("error"))
    err = len(results) - ok
    log.info(f"Done — {ok} succeeded, {err} failed. Results in: {output_dir}")

    if err:
        sys.exit(1)


if __name__ == "__main__":
    main()
