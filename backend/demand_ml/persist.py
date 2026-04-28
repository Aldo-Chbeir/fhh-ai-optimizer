"""joblib model persistence — Prophet objects pickle cleanly."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import joblib


def save(obj: Any, path: Path | str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(obj, p)


def load(path: Path | str) -> Any:
    return joblib.load(path)


def exists(path: Path | str) -> bool:
    return Path(path).exists()
