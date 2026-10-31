"""Build-time only download. The installed app never fetches models."""
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def extract(archive, destination, root):
    # Never extract links, devices, absolute paths, or entries outside the expected root.
    with tarfile.open(archive, "r:bz2") as source:
        members = source.getmembers()
        if sum(m.size for m in members) > 4_000_000_000:
            raise ValueError("Model archive is unexpectedly large")
        for member in members:
            path = Path(member.name)
            if (path.is_absolute() or ".." in path.parts or not path.parts
                    or path.parts[0] != root or not (member.isfile() or member.isdir())):
                raise ValueError("Unsafe model archive entry: " + member.name)
        source.extractall(destination, members=members)


def main():
    models = ROOT / "models"
    models.mkdir(exist_ok=True)
    spec = json.loads((ROOT / "models.json").read_text())["asr"]
    final = models / spec["directory"]
    stamp = final / ".archive-sha256"
    if (stamp.exists() and stamp.read_text().strip() == spec["sha256"]
            and all((final / name).exists() for name in spec["required"])):
        print("Speech model already installed")
        return
    with tempfile.TemporaryDirectory(dir=models) as temporary:
        stage = Path(temporary)
        archive = stage / "model.tar.bz2"
        print("Downloading " + spec["directory"], flush=True)
        with urllib.request.urlopen(spec["url"], timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        if archive.stat().st_size != spec["bytes"] or sha256(archive) != spec["sha256"]:
            raise ValueError("Checksum mismatch for the speech model")
        extract(archive, stage, spec["directory"])
        candidate = stage / spec["directory"]
        if not all((candidate / name).exists() for name in spec["required"]):
            raise ValueError("Incomplete speech model")
        (candidate / ".archive-sha256").write_text(spec["sha256"] + "\n")
        if final.exists():
            raise FileExistsError("Remove the incomplete model directory before retrying: " + str(final))
        candidate.rename(final)
    print("Speech model is ready for offline packaging.")


if __name__ == "__main__":
    main()
