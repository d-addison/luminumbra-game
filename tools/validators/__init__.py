"""Validator registry for content files.

Each module in this package is discovered with pkgutil.iter_modules and
imported as validators.<name>. A module may define two dict attributes:

SCHEMAS: dict[str, callable]
    Maps a schema id, for example "luminumbra.game.<kind>.v1", to
    fn(path, obj, ctx) -> list[str]. Called for each .json file whose top-level
    "schema" key equals that id and whose path matches no GLOBS pattern. obj is
    the parsed JSON object.

GLOBS: dict[str, callable]
    Maps an fnmatch pattern, relative to ROOT with posix separators, to
    fn(path, text, ctx) -> list[str]. Used for files that cannot carry a
    "schema" key, such as engine-format presets and .traversal files. text is
    the file decoded as UTF-8. A file matched by a glob is not required to have
    a "schema" key.

Every path argument is the posix path relative to ROOT. ctx is a Context with
the absolute root, allow_pending and release. Problems are strings of the form
"PATH: reason". A validator that raises is reported by the caller as a problem.

Schema ids and glob patterns must be unique across all modules. discover()
raises RegistryError on a duplicate, an import failure or a malformed table.
"""

import importlib
import pkgutil
from dataclasses import dataclass
from typing import Optional


class RegistryError(Exception):
    """A validator module could not be imported or registered."""


@dataclass(frozen=True)
class Context:
    root: str
    allow_pending: bool
    release: bool
    expected_engine_revision: Optional[str] = None
    expected_game_revision: Optional[str] = None
    artifact_root: Optional[str] = None


def _table(module, attr):
    value = getattr(module, attr, {})
    if not isinstance(value, dict):
        raise RegistryError(f"{module.__name__}: {attr} must be a dict")
    for key, fn in value.items():
        if not isinstance(key, str) or not callable(fn):
            raise RegistryError(
                f"{module.__name__}: {attr} entry {key!r} must map a string to a callable"
            )
    return value


def discover():
    """Import every validator module and return the merged (schemas, globs) dicts."""
    schemas = {}
    globs = {}
    schema_origin = {}
    glob_origin = {}
    for info in sorted(pkgutil.iter_modules(__path__), key=lambda item: item.name):
        full_name = f"{__name__}.{info.name}"
        try:
            module = importlib.import_module(full_name)
        except Exception as exc:
            raise RegistryError(f"{full_name}: import failed: {exc}") from exc
        for key, fn in _table(module, "SCHEMAS").items():
            if key in schemas:
                raise RegistryError(
                    f"duplicate schema {key!r} in {schema_origin[key]} and {full_name}"
                )
            schemas[key] = fn
            schema_origin[key] = full_name
        for key, fn in _table(module, "GLOBS").items():
            if key in globs:
                raise RegistryError(
                    f"duplicate glob {key!r} in {glob_origin[key]} and {full_name}"
                )
            globs[key] = fn
            glob_origin[key] = full_name
    return schemas, globs
