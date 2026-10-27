import sys, subprocess, io, tarfile, json, hashlib, gzip, time


def main(image: str, dst: str) -> int:
    # 1) docker save to memory (no intermediate file on disk)
    proc = subprocess.run(["docker", "save", image], capture_output=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stderr.decode("utf-8", "replace"))
        return proc.returncode

    with tarfile.open(fileobj=io.BytesIO(proc.stdout), mode="r:*") as tin:
        manifest = json.load(tin.extractfile("manifest.json"))
        entry = manifest[0]
        repo_tags = entry.get("RepoTags") or []
        config_bytes = tin.extractfile(entry["Config"]).read()
        config_id = hashlib.sha256(config_bytes).hexdigest()
        layers = []  # (id, raw_or_gz_bytes, is_gzipped)
        for p in entry.get("Layers", []):
            b = tin.extractfile(p).read()
            layers.append((hashlib.sha256(b).hexdigest(), b, b[:2] == b"\x1f\x8b"))

    repo, tag = (repo_tags[0].split(":", 1) + [""])[:2] if repo_tags else ("", "")
    created = time.strftime("%Y-%m-%dT:%M:%SZ", time.gmtime())
    try:
        if json.loads(config_bytes).get("created"):
            created = json.loads(config_bytes)["created"]
    except Exception:
        pass

    top_layer_id = layers[-1][0] if layers else ""
    with tarfile.open(dst, "w") as tout:
        def add(name: str, data: bytes, mode: int = 0o644) -> None:
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode, ti.mtime = len(data), mode, 0
            tout.addfile(ti, io.BytesIO(data))

        add(f"{config_id}.json", config_bytes)
        prev = ""
        for lid, b, is_gz in layers:
            add(f"{lid}/layer.tar", b if is_gz else gzip.compress(b))
            meta = {"id": lid, "created": created, "container_config": {}}
            if prev:
                meta["parent"] = prev
            add(f"{lid}/json", json.dumps(meta, separators=(",", ":")).encode("utf-8"))
            add(f"{lid}/VERSION", b"1.0")
            prev = lid
        add("manifest.json", json.dumps(
            [{"Config": f"{config_id}.json", "RepoTags": repo_tags,
              "Layers": [f"{lid}/layer.tar" for lid, _, _ in layers]}],
            separators=(",", ":")).encode("utf-8"))
        add("repositories", json.dumps(
            {repo: {tag: top_layer_id}} if repo else {},
            separators=(",", ":")).encode("utf-8"))

    print("OK", dst)
    print("config_id", config_id)
    print("layers", len(layers), "all_gzipped", all(g for _, _, g in layers))
    print("repo_tags", repo_tags)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python build_legacy_image.py <image[:tag]> <output.tar>")
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))