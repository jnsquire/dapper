# Variable Presentation

Dapper returns rich display hints alongside every variable so that DAP clients
(VS Code, etc.) can render them with appropriate icons, badges, and visibility
controls.  This page documents what hints are produced and how structured
Python types are handled.

---

## Presentation hint fields

Every `Variable` object Dapper sends includes a `presentationHint` map with some
or all of the following keys:

| Field | Values | Meaning |
|---|---|---|
| `kind` | `data`, `property`, `method`, `class` | Semantic category — used for icons in the variables panel |
| `attributes` | `hasSideEffects`, `hasDataBreakpoint`, `rawString`, … | Badges or flags rendered next to the value |
| `visibility` | `public`, `private` | Variables whose names start with `_` are marked `private` |

### `kind` mapping

| Python value | `kind` |
|---|---|
| Integer, float, `None`, list, dict, … | `data` |
| Dataclass / namedtuple / Pydantic field | `property` |
| Callable (function, lambda, method) | `method` |
| Class object (`type` instance) | `class` |

### `attributes` mapping

| Condition | Attribute added |
|---|---|
| Value is callable | `hasSideEffects` |
| Variable is registered as a data watchpoint | `hasDataBreakpoint` |
| String/bytes value contains newlines or exceeds display limit | `rawString` |

---

## Structured model rendering

Dapper detects three families of structured model and expands them by **declared
field** rather than via the generic `dir()` traversal. This means:

- Only the named fields are shown (no `__dunder__` noise).
- Fields appear in **declaration order**.  
- Each field carries `presentationHint.kind = "property"`.
- The `type` label includes the model family, e.g. `"dataclass Point"`.
- The `namedVariables` count is set so clients display a field-count badge.

### Supported types

#### `dataclasses.dataclass`

```python
from dataclasses import dataclass

@dataclass
class Point:
    x: float
    y: float

p = Point(1.0, 2.0)
```

Variables panel shows:

```
p    Point(x=1.0, y=2.0)    dataclass Point   [2 fields]
 ├─ x    1.0    float
 └─ y    2.0    float
```

#### `collections.namedtuple` / `typing.NamedTuple`

```python
from typing import NamedTuple

class Coordinate(NamedTuple):
    lat: float
    lon: float
    alt: float = 0.0
```

Fields are shown in definition order; the tuple indices are hidden.

#### Pydantic models (v1 and v2)

```python
from pydantic import BaseModel

class User(BaseModel):
    name: str
    age: int
    email: str
```

Variables panel shows:

```
user    name='Alice' age=30 …    pydantic User   [3 fields]
 ├─ name     'Alice'    str
 ├─ age      30         int
 └─ email    '…'        str
```

Pydantic detection is **duck-typed** — Dapper checks for `model_fields` (v2) or
`__fields__` + `__validators__` (v1) without importing Pydantic at the adapter
level, so the Pydantic package is optional.

---

## Visibility

Variable names beginning with `_` are marked `visibility: private` and may be
hidden or de-emphasised by the client (VS Code folds them into a separate
collapsible section).

Names not starting with `_` are marked `visibility: public`.

---

## Expanding nested structures

Dapper allocates a non-zero `variablesReference` for any value that can be
expanded:

- `dict`, `list`, `tuple`
- Objects with a `__dict__` (arbitrary instances)
- Dataclasses, namedtuples, and Pydantic models (field-aware expansion, see above)

Click the expand arrow in the Variables panel to fetch child variables on demand.

---

## Related

- [Async Debugging](async-debugging.md) — asyncio task inspector and async-aware stepping.  
- [Debugger Features Checklist](checklist.md) — full implementation status matrix.
- [Frame Evaluation Guide](../getting-started/frame-eval/index.md) — expression evaluation during debugging.
