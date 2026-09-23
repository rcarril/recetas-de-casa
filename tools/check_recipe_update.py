#!/usr/bin/env python3
"""Check the scope of a recipe-only update after running tools/build.py."""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent.parent


def git(*args):
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args], capture_output=True, check=False
    )
    if result.returncode:
        raise ValueError(result.stderr.decode("utf-8", errors="replace").strip())
    return result.stdout


def changed_paths(*args):
    fields = git("diff", "--no-ext-diff", "--no-renames", "--name-status", "-z", *args, "--").split(b"\0")
    changes = {}
    for offset in range(0, len(fields) - 1, 2):
        status = fields[offset].decode("ascii")
        path = fields[offset + 1].decode("utf-8")
        if status != "M":
            raise ValueError(f"Solo se permiten modificaciones; encontrado {status}: {path}")
        changes[path] = status
    return set(changes)


def metadata(source, name):
    match = re.fullmatch(r"---\r?\n(.*?)\r?\n---\r?\n(.*)", source, re.DOTALL)
    if not match:
        raise ValueError(f"{name}: falta la cabecera YAML.")
    data = yaml.safe_load(match.group(1))
    if not isinstance(data, dict):
        raise ValueError(f"{name}: la cabecera YAML no es un objeto.")
    if not isinstance(data.get("id"), str) or not data["id"].strip():
        raise ValueError(f"{name}: falta el ID de la receta.")
    if type(data.get("version")) is not int:
        raise ValueError(f"{name}: version debe ser un entero.")
    return data


def check(base, recipes):
    repository = Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve()
    if repository != ROOT:
        raise ValueError("La guardia debe estar en tools/ del repositorio público.")
    commit = git("rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}").decode().strip()
    pairs = {}
    original = {}
    for name in recipes:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*\.md", name):
            raise ValueError(f"Nombre de receta no válido: {name!r}")
        source = f"recetas/{name}"
        rendered = f"docs/recetas/{Path(name).stem}.html"
        for relative in (source, rendered):
            path = ROOT / relative
            if not path.is_file() or path.resolve() != path:
                raise ValueError(f"Debe existir un archivo regular sin enlaces simbólicos: {relative}")
            entry = git("ls-tree", "-z", commit, "--", relative)
            if not entry.startswith(b"100644 blob "):
                raise ValueError(f"El archivo debe existir como archivo regular en la base: {relative}")
        pairs[source] = rendered
        original[source] = git("show", f"{commit}:{source}").decode("utf-8")

    untracked = git("ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").strip("\0")
    if untracked:
        raise ValueError("Archivos sin seguimiento inesperados: " + ", ".join(untracked.split("\0")))

    # Include the index: a staged change must not hide behind an unstaged reversal.
    working_changes = changed_paths(commit)
    staged_changes = changed_paths("--cached", commit)
    changes = working_changes | staged_changes
    allowed = set(pairs) | set(pairs.values())
    unexpected = changes - allowed
    if unexpected:
        raise ValueError("Cambios fuera de las recetas autorizadas: " + ", ".join(sorted(unexpected)))
    if not changes:
        return "NO_CHANGES"

    updated = []
    for source, rendered in pairs.items():
        if source not in changes and rendered not in changes:
            continue
        if source not in working_changes or rendered not in working_changes:
            raise ValueError(f"Deben cambiar juntos la ficha y su HTML: {source}, {rendered}")
        before = metadata(original[source], source)
        after = metadata((ROOT / source).read_text(encoding="utf-8"), source)
        if after["id"] != before["id"]:
            raise ValueError(f"{source}: el ID debe conservarse.")
        if after["version"] != before["version"] + 1:
            raise ValueError(f"{source}: version debe aumentar exactamente en uno.")
        if after.get("estado") != before.get("estado"):
            raise ValueError(f"{source}: una actualización automática no cambia el estado de validación.")
        updated.append(Path(source).name)
    return "OK: " + ", ".join(sorted(updated))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="Commit anterior a la actualización.")
    parser.add_argument("--recipe", action="append", required=True, help="Nombre de ficha autorizada; repetible.")
    args = parser.parse_args()
    try:
        print(check(args.base, args.recipe))
    except (ValueError, OSError, UnicodeError, yaml.YAMLError) as error:
        print(f"REJECTED: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
