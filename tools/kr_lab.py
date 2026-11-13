"""Kingdom Rush TAS lab: read-only discovery, isolated copies, trace comparison.

Python standard library only. Never patches the installed game.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
APP_ID = "246420"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def steam_libraries() -> list[Path]:
    roots = [Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Steam"]
    if sys.platform == "win32":
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                roots.insert(0, Path(winreg.QueryValueEx(key, "SteamPath")[0]))
        except OSError:
            pass
    for root in list(roots):
        vdf = root / "steamapps/libraryfolders.vdf"
        if vdf.exists():
            for value in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8")):
                roots.append(Path(value.replace("\\\\", "\\")))
    return list(dict.fromkeys(p.resolve() for p in roots if p.exists()))


def discover() -> dict:
    libraries = steam_libraries()
    games = []
    for library in libraries:
        manifest = library / f"steamapps/appmanifest_{APP_ID}.acf"
        if not manifest.exists():
            continue
        fields = dict(re.findall(r'"([^"\n]+)"\s+"([^"\n]*)"', manifest.read_text(encoding="utf-8")))
        game = library / "steamapps/common" / fields.get("installdir", "Kingdom Rush")
        games.append({"directory": str(game), "manifest": str(manifest),
                      "build_id": fields.get("buildid"), "state_flags": fields.get("StateFlags"),
                      "exists": game.exists()})
    return {"app_id": APP_ID, "libraries": list(map(str, libraries)), "games": games}


def inspect_game(directory: Path) -> dict:
    directory = directory.resolve(strict=True)
    files = []
    for path in sorted(directory.iterdir()):
        if not path.is_file():
            continue
        info = {"name": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)}
        if path.suffix.lower() in (".exe", ".love") and zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                entries = []
                for item in z.infolist():
                    if item.filename.endswith(".lua"):
                        with z.open(item) as f:
                            signature = f.read(4)
                        entries.append({"name": item.filename, "bytes": item.file_size,
                                        "kind": "luajit" if signature.startswith(b"\x1bLJ") else "lua"})
                info["archive"] = {"entry_count": len(z.infolist()), "lua": entries}
        files.append(info)
    return {"directory": str(directory), "files": files}


def prepare(directory: Path, name: str) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", name):
        raise ValueError("Workspace name must contain only letters, digits, underscores or hyphens")
    source = directory.resolve(strict=True)
    target = ROOT / "lab" / name
    if target.exists():
        raise ValueError(f"Refusing to overwrite existing lab: {target}")
    # Resolve both directions to avoid copying a workspace into itself.
    resolved = target.resolve()
    if resolved == source or source in resolved.parents or resolved in source.parents:
        raise ValueError("Source and destination must be disjoint")
    inventory = inspect_game(source)
    if not any(f.get("archive") for f in inventory["files"]):
        raise ValueError("No LÖVE fused executable/archive found; refusing unverified game layout")
    target.mkdir(parents=True)
    shutil.copytree(source, target / "game")
    # This is a backup only. A fresh isolated profile will be used for experiments.
    save = Path(os.environ.get("APPDATA", "")) / "kingdom_rush"
    if save.is_dir():
        shutil.copytree(save, target / "original-save-backup")
    (target / "baseline.json").write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    copied = inspect_game(target / "game")
    if inventory["files"] != copied["files"]:
        raise ValueError("Copied files do not match source hashes")
    return {"lab": str(target), "original_unchanged": True, "copy_verified": True}


def compare_traces(left: Path, right: Path) -> dict:
    # Exact comparison, including metadata and terminal status. Never accept a
    # matching prefix or a missing ending as a successful replay.
    def read(path):
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows or rows[0].get("type") != "metadata":
            raise ValueError(f"Missing metadata: {path}")
        if rows[-1].get("type") != "end" or rows[-1].get("completed") is not True:
            raise ValueError(f"Incomplete trace: {path}")
        return rows
    a, b = read(left), read(right)
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            return {"match": False, "row": i + 1, "left": x, "right": y}
    if len(a) != len(b):
        return {"match": False, "reason": "different lengths", "left_rows": len(a), "right_rows": len(b)}
    return {"match": True, "rows": len(a)}


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("discover")
    inspect = sub.add_parser("inspect")
    inspect.add_argument("directory", type=Path)
    inspect.add_argument("--output", type=Path)
    prep = sub.add_parser("prepare")
    prep.add_argument("directory", type=Path)
    prep.add_argument("--name", required=True)
    cmp = sub.add_parser("compare")
    cmp.add_argument("left", type=Path)
    cmp.add_argument("right", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "discover":
            result = discover()
        elif args.command == "inspect":
            result = inspect_game(args.directory)
        elif args.command == "prepare":
            result = prepare(args.directory, args.name)
        else:
            result = compare_traces(args.left, args.right)
        output = json.dumps(result, ensure_ascii=False, indent=2)
        if getattr(args, "output", None):
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output)
        return 1 if result.get("match") is False else 0
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
