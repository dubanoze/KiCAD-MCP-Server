"""Update a schematic's cached symbol definitions from their source libraries.

Equivalent of eeschema's "Update Symbols from Library": ERC reads each symbol's
definition from the schematic's (lib_symbols ...) cache, and flags
`lib_symbol_mismatch` when that cache differs from the current library symbol
(common after kicad-skip / EasyEDA imports that drop properties KiCad 10 expects).

This re-reads the library symbol and overwrites the cache entry verbatim (only the
top-level name is rewritten to the full "Nickname:Name" lib_id), so the cache
matches the library again. Optionally prunes cache entries no instance references.

All file mutation goes through the central save hook (pretty-printing on dump).
"""

import copy
import glob
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import sexpdata
from sexpdata import Symbol

logger = logging.getLogger(__name__)

_SYM = Symbol("symbol")
_LIB_SYMBOLS = Symbol("lib_symbols")
_LIB_ID = Symbol("lib_id")
_PROPERTY = Symbol("property")


def _expand_uri(uri: str, kiprjmod: str) -> str:
    """Expand ${KIPRJMOD} and ${ENV} placeholders in a sym-lib-table URI."""
    uri = uri.replace("${KIPRJMOD}", kiprjmod).replace("$(KIPRJMOD)", kiprjmod)

    def _sub(m):
        var = m.group(1)
        return os.environ.get(var, m.group(0))

    uri = re.sub(r"\$\{([^}]+)\}", _sub, uri)
    uri = re.sub(r"\$\(([^)]+)\)", _sub, uri)
    return os.path.normpath(uri.replace("\\", "/"))


def _parse_lib_table(table_path: Path, kiprjmod: str) -> Dict[str, str]:
    """Parse a sym-lib-table into {nickname: resolved_file_path}."""
    libs: Dict[str, str] = {}
    try:
        data = sexpdata.loads(table_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Could not parse lib table {table_path}: {e}")
        return libs
    lib_sym = Symbol("lib")
    name_sym = Symbol("name")
    uri_sym = Symbol("uri")
    for item in data:
        if not (isinstance(item, list) and item and item[0] == lib_sym):
            continue
        name = uri = None
        for field in item[1:]:
            if isinstance(field, list) and len(field) >= 2:
                if field[0] == name_sym:
                    name = str(field[1])
                elif field[0] == uri_sym:
                    uri = str(field[1])
        if name and uri:
            libs[name] = _expand_uri(uri, kiprjmod)
    return libs


def _discover_global_tables() -> List[Path]:
    """Find KiCad's global sym-lib-table(s) from config dirs."""
    candidates: List[Path] = []
    roots = []
    cfg_home = os.environ.get("KICAD_CONFIG_HOME")
    if cfg_home:
        roots.append(Path(cfg_home))
    appdata = os.environ.get("APPDATA")
    if appdata:
        roots.append(Path(appdata) / "kicad")
    # Linux/macOS fallbacks
    home = os.environ.get("HOME") or os.path.expanduser("~")
    if home:
        roots.append(Path(home) / ".config" / "kicad")
        roots.append(Path(home) / "Library" / "Preferences" / "kicad")
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(glob.glob(str(root / "*" / "sym-lib-table"))) + [str(root / "sym-lib-table")]:
            pp = Path(p)
            if pp.is_file() and pp not in candidates:
                candidates.append(pp)
    return candidates


def _build_resolver(
    schematic_path: Path, extra_tables: Optional[List[str]] = None
) -> Dict[str, str]:
    """nickname -> library file. Project table wins over global on collision."""
    kiprjmod = str(schematic_path.parent).replace("\\", "/")
    resolver: Dict[str, str] = {}
    # Global first (lowest priority); project then extras override on collision.
    for gt in _discover_global_tables():
        resolver.update(_parse_lib_table(gt, kiprjmod))
    # project table overrides
    for tbl in [schematic_path.parent / "sym-lib-table", *(schematic_path.parents)]:
        cand = tbl if str(tbl).endswith("sym-lib-table") else tbl / "sym-lib-table"
        if Path(cand).is_file():
            resolver.update(_parse_lib_table(Path(cand), kiprjmod))
            break
    for et in extra_tables or []:
        if Path(et).is_file():
            resolver.update(_parse_lib_table(Path(et), kiprjmod))
    return resolver


def _load_library(path: str, _cache: Dict[str, list]) -> Optional[list]:
    if path in _cache:
        return _cache[path]
    try:
        data = sexpdata.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"Could not load library {path}: {e}")
        data = None
    _cache[path] = data
    return data


def _find_symbol(lib_data: list, name: str) -> Optional[list]:
    for item in lib_data[1:] if lib_data else []:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and item[0] == _SYM
            and str(item[1]) == name
        ):
            return item
    return None


def _used_lib_ids(sch_data: list) -> Dict[str, List[str]]:
    """{lib_id: [refs...]} for placed instances (top-level (symbol (lib_id ..)) )."""
    used: Dict[str, List[str]] = {}
    for item in sch_data:
        if not (isinstance(item, list) and item and item[0] == _SYM):
            continue
        lib_id = ref = None
        for f in item[1:]:
            if not (isinstance(f, list) and f):
                continue
            if f[0] == _LIB_ID and len(f) >= 2:
                lib_id = str(f[1])
            elif f[0] == _PROPERTY and len(f) >= 3 and str(f[1]) == "Reference":
                ref = str(f[2])
        if lib_id:
            used.setdefault(lib_id, []).append(ref or "?")
    return used


class SymbolUpdater:
    @staticmethod
    def update_from_library(
        schematic_path: Path,
        only_lib_ids: Optional[List[str]] = None,
        only_refs: Optional[List[str]] = None,
        prune_unused: bool = False,
        extra_tables: Optional[List[str]] = None,
    ) -> Dict:
        """Refresh cached symbol definitions from their source libraries.

        Returns a summary dict: updated/added/unresolved/not_found/pruned lists.
        """
        result = {
            "success": False,
            "updated": [],
            "added": [],
            "unresolved": [],
            "not_found": [],
            "pruned": [],
            "skipped": [],
        }
        try:
            sch_data = sexpdata.loads(schematic_path.read_text(encoding="utf-8"))
            lib_symbols = next(
                (it for it in sch_data
                 if isinstance(it, list) and it and it[0] == _LIB_SYMBOLS),
                None,
            )
            if lib_symbols is None:
                result["message"] = "No (lib_symbols ...) block in schematic"
                return result

            used = _used_lib_ids(sch_data)
            used_ids = set(used.keys())

            # Determine which lib_ids to refresh.
            targets = set(used_ids)
            if only_refs:
                want_refs = set(only_refs)
                targets = {
                    lid for lid, refs in used.items()
                    if any(r in want_refs for r in refs)
                }
            if only_lib_ids:
                targets &= set(only_lib_ids)

            resolver = _build_resolver(schematic_path, extra_tables)
            lib_cache: Dict[str, list] = {}

            for lib_id in sorted(targets):
                if ":" not in lib_id:
                    result["skipped"].append(lib_id)
                    continue
                nick, name = lib_id.split(":", 1)
                lib_file = resolver.get(nick)
                if not lib_file or not Path(lib_file).is_file():
                    result["unresolved"].append(lib_id)
                    continue
                lib_data = _load_library(lib_file, lib_cache)
                src = _find_symbol(lib_data, name) if lib_data else None
                if src is None:
                    result["not_found"].append(lib_id)
                    continue
                fresh = copy.deepcopy(src)
                fresh[1] = lib_id  # top-level name -> full "Nickname:Name"

                # Replace existing cache entry in place, else append.
                replaced = False
                for i, it in enumerate(lib_symbols):
                    if (
                        isinstance(it, list) and len(it) >= 2
                        and it[0] == _SYM and str(it[1]) == lib_id
                    ):
                        lib_symbols[i] = fresh
                        replaced = True
                        break
                if replaced:
                    result["updated"].append(lib_id)
                else:
                    lib_symbols.append(fresh)
                    result["added"].append(lib_id)

            if prune_unused:
                keep = []
                for it in lib_symbols:
                    if (
                        isinstance(it, list) and len(it) >= 2
                        and it[0] == _SYM and ":" in str(it[1])
                        and str(it[1]) not in used_ids
                    ):
                        result["pruned"].append(str(it[1]))
                        continue
                    keep.append(it)
                lib_symbols[:] = keep

            schematic_path.write_text(sexpdata.dumps(sch_data), encoding="utf-8")
            result["success"] = True
            result["message"] = (
                f"updated {len(result['updated'])}, added {len(result['added'])}, "
                f"pruned {len(result['pruned'])}, unresolved {len(result['unresolved'])}, "
                f"not_found {len(result['not_found'])}"
            )
            return result
        except Exception as e:
            import traceback
            logger.error(traceback.format_exc())
            result["message"] = str(e)
            return result
