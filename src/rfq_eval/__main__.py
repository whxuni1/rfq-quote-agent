"""Command line entry for the RFQ evaluation."""

import argparse
import sys
from pathlib import Path

from rfq_eval.adapt import ProductAdapter
from rfq_eval.dataset_io import load_dataset, materialize
from rfq_eval.report import write_outputs
from rfq_eval.runner import evaluate
from rfq_eval.versions import repo_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the RFQ quote agent against labeled cases.")
    parser.add_argument("--out", type=Path, default=None, help="Directory for the report and failure corpus.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 when the product is not production-ready. Default writes the report and exits 0.",
    )
    args = parser.parse_args(argv)
    out = args.out if args.out is not None else repo_root() / "eval"
    materialize()
    dataset = load_dataset()
    report, failures = evaluate(dataset, ProductAdapter(), out / "work")
    write_outputs(report, failures, out)
    print(report.decision_summary)
    if args.strict and not report.production_ready:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
