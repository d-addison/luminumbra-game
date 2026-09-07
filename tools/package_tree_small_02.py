#!/usr/bin/env python3
"""Build the runtime archive and its pinned engine acquisition manifest entry."""
import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile


def identity(data):
    return {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = json.loads((args.runtime / "conversion-receipt.json").read_text())
    payloads = {}
    files = []
    for item in receipt["files"]:
        path = Path(item["path"])
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Unsafe conversion receipt path")
        data = (args.runtime / path).read_bytes()
        if any(identity(data)[key] != item[key] for key in ["size", "sha256"]):
            raise ValueError(f"Runtime bytes changed: {path}")
        payloads[path.as_posix()] = data
        files.append(item)
    for name, path in {
        "conversion-receipt.json": args.runtime / "conversion-receipt.json",
        "source-manifest.json": args.source / "source-manifest.json",
        "LICENSE.txt": args.source / "LICENSE.txt",
        "CONVERSION.md": Path(__file__).resolve().parent.parent / "assets/tree-small-02/CONVERSION.md",
    }.items():
        data = path.read_bytes()
        payloads[name] = data
        files.append({"path": name, **identity(data)})
    archive_bytes = io.BytesIO()
    with tarfile.open(fileobj=archive_bytes, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for name, data in sorted(payloads.items()):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o644
            info.mtime = 0
            tar.addfile(info, io.BytesIO(data))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0, compresslevel=9) as compressed:
            compressed.write(archive_bytes.getvalue())
    entry = {
        "version": "1.0.0", "install_dir": "game-assets/tree-small-02/1.0.0",
        "archive": {
            "url": "https://github.com/d-addison/luminumbra-game/releases/download/tree-small-02-runtime-v1.0.0/tree-small-02-runtime-v1.0.0.tar.gz",
            **identity(args.output.read_bytes()), "uncompressed_size": archive_bytes.tell(),
        },
        "files": sorted(files, key=lambda item: item["path"]),
    }
    args.output.with_suffix(args.output.suffix + ".manifest.json").write_text(json.dumps(entry, indent=2) + "\n")
    print(json.dumps(entry["archive"], indent=2))


if __name__ == "__main__":
    main()
