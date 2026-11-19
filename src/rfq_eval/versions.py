"""Record harness, dataset, model, and prompt versions for a run."""

import hashlib
import os
import subprocess
from pathlib import Path

from rfq_eval import __version__
from rfq_eval.schema import VersionStamp
from rfq_eval.thresholds import REQUIRED_PROMPT_FILES


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def git_sha(root: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def prompt_state(root: Path) -> tuple[dict[str, str], list[str]]:
    prompt_dir = root / "src" / "rfq_agent" / "prompts"
    hashes: dict[str, str] = {}
    missing: list[str] = []
    for name in REQUIRED_PROMPT_FILES:
        path = prompt_dir / name
        if not path.is_file():
            missing.append(name)
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        hashes[name] = digest
    return hashes, missing


def version_stamp(
    dataset_version: str,
    *,
    dataset_sha256: str,
    reported_model_id: str | None,
    price_models: list[str],
) -> VersionStamp:
    root = repo_root()
    hashes, missing = prompt_state(root)
    model_id = os.environ.get("RFQ_AGENT_MODEL")
    source: str = "env" if model_id else "absent"
    return VersionStamp(
        harness_version=__version__,
        dataset_version=dataset_version,
        dataset_sha256=dataset_sha256,
        git_sha=git_sha(root),
        model_id=model_id,
        model_source="env" if source == "env" else "absent",
        reported_model_id=reported_model_id,
        prompt_hashes=hashes,
        missing_prompt_files=missing,
        price_card_models=price_models,
    )
