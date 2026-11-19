"""Read and write the labeled dataset."""

import hashlib
import json
from pathlib import Path

from rfq_eval.case_library import build_dataset
from rfq_eval.schema import EvalDataset
from rfq_eval.versions import repo_root


def dataset_dir() -> Path:
    return repo_root() / "eval" / "dataset"


def canonical_json(dataset: EvalDataset) -> str:
    return dataset.model_dump_json()


def dataset_sha256(dataset: EvalDataset) -> str:
    return hashlib.sha256(canonical_json(dataset).encode("utf-8")).hexdigest()


def load_or_materialize(directory: Path | None = None, *, regenerate: bool = False) -> EvalDataset:
    """Load persisted labels.

    Regeneration is explicit. A directory with no manifest is a first run and
    is written from the generator. An existing manifest is never replaced,
    including when it is malformed.
    """
    root = directory if directory is not None else dataset_dir()
    if regenerate or not (root / "manifest.json").is_file():
        materialize(directory=root)
    return load_dataset(root)


def materialize(dataset: EvalDataset | None = None, directory: Path | None = None) -> Path:
    source = dataset if dataset is not None else build_dataset()
    root = directory if directory is not None else dataset_dir()
    if root.exists():
        for child in root.rglob("*"):
            if child.is_file():
                child.unlink()
    documents = root / "documents"
    documents.mkdir(parents=True, exist_ok=True)
    payload = json.loads(canonical_json(source))
    if not isinstance(payload, dict):
        raise TypeError("dataset payload must be an object")
    _write_json(root / "manifest.json", payload["manifest"])
    _write_json(root / "gates.json", payload["gates"])
    _write_json(root / "costs.json", payload["costs"])
    _write_json(root / "recovery.json", payload["recovery"])
    _write_json(root / "isolation.json", payload["isolation"])
    _write_json(root / "price_card.json", payload["price_card"])
    document_rows = payload["documents"]
    if not isinstance(document_rows, list):
        raise TypeError("documents payload must be a list")
    for row in document_rows:
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise TypeError("document case is missing case_id")
        _write_json(documents / f"{row['case_id']}.json", row)
    schema = EvalDataset.model_json_schema()
    (root / "schema.json").write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return root


def load_dataset(directory: Path | None = None) -> EvalDataset:
    root = directory if directory is not None else dataset_dir()
    documents = [_read_json(path) for path in sorted((root / "documents").glob("*.json"))]
    payload = {
        "manifest": _read_json(root / "manifest.json"),
        "documents": documents,
        "gates": _read_json(root / "gates.json"),
        "costs": _read_json(root / "costs.json"),
        "recovery": _read_json(root / "recovery.json"),
        "isolation": _read_json(root / "isolation.json"),
        "price_card": _read_json(root / "price_card.json"),
    }
    return EvalDataset.model_validate(payload)


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> object:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    return loaded
