"""Read and write the JSON artifacts under runs/ and results/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, TypeVar

from pydantic import BaseModel, TypeAdapter

M = TypeVar("M", bound=BaseModel)


def save_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json")
    elif isinstance(payload, list):
        payload = [item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in payload]
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return path


def load_model(path: Path, model: type[M]) -> M:
    return model.model_validate_json(path.read_text())


def load_models(path: Path, model: type[M]) -> list[M]:
    return TypeAdapter(list[model]).validate_json(path.read_text())


def append_jsonl(path: Path, record) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(record, BaseModel):
        record = record.model_dump(mode="json")
    with path.open("a") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def save_jsonl(path: Path, records: Iterable[BaseModel]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(record.model_dump_json() + "\n" for record in records))
    return path


def load_jsonl(path: Path, model: type[M]) -> list[M]:
    return [model.model_validate_json(line) for line in path.read_text().splitlines() if line.strip()]
