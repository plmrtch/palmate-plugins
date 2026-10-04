"""Generate identical self-contained host references from one reviewed source."""
import argparse
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def generated():
    source = (ROOT / "shared/development-workflow.md").read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    return f"<!-- Generated from shared/development-workflow.md; sha256:{digest} -->\n".encode() + source


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--backend", type=Path, help="Also export pinned checkout guides into this agent_backend clone")
    args = parser.parse_args()
    content = generated()
    for host in ("codex", "claude-code"):
        target = ROOT / host / "skills/palmate-workflow/references/development-workflow.md"
        if args.check:
            if not target.is_file() or target.read_bytes() != content:
                raise SystemExit(f"stale development guidance for {host}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    if args.backend:
        backend = args.backend.resolve()
        if not (backend / "repo/branching/content/assets").is_dir() or not (backend / "palmate_cli/palmate_cli/assets").is_dir():
            raise SystemExit("backend target is not an agent_backend checkout")
        source = (ROOT / "shared/project-guide.md").read_bytes()
        digest = hashlib.sha256(source).hexdigest()
        guide = f"<!-- Generated from palmate-plugins/shared/project-guide.md; sha256:{digest} -->\n".encode() + source
        claude = f"<!-- Palmate development-v1 guide sha256:{digest} -->\n@AGENTS.md\n".encode()
        for directory in (backend / "repo/branching/content/assets", backend / "palmate_cli/palmate_cli/assets"):
            for name, data in (("AGENTS.md", guide), ("CLAUDE.md", claude)):
                target = directory / name
                if args.check:
                    if not target.is_file() or target.read_bytes() != data:
                        raise SystemExit(f"stale checkout guide: {target}")
                else:
                    target.write_bytes(data)


if __name__ == "__main__":
    main()
