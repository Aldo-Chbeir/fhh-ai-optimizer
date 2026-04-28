"""joblib-backed model persistence."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib


def save(obj: Any, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(obj, path)


def load(path: Path | str) -> Any:
    return joblib.load(path)


def exists(path: Path | str) -> bool:
    return Path(path).exists()
