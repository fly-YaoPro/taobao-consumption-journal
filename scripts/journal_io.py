"""Local atomic state and confined paths shared by optional execution helpers."""
import json
import os
from pathlib import Path
import re


def load(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.is_file() else default


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + '.part')
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(part, path)


def local(root, name, exists=True):
    if not isinstance(name, str) or not name or '\\' in name or re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:', name):
        raise ValueError('expected project-relative path')
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or (exists and not path.is_file()):
        raise ValueError('missing file or path outside project: ' + str(name))
    return path
