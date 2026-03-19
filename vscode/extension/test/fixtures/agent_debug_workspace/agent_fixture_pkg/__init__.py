from __future__ import annotations

from pathlib import Path
from pkgutil import extend_path

__path__ = extend_path(__path__, __name__)  # type: ignore[name-defined]

src_package = Path(__file__).resolve().parent.parent / "src" / __name__
if src_package.is_dir():
    __path__.append(str(src_package))
