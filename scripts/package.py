"""Build a plugin ZIP from tracked runtime files without publishing it."""
from pathlib import Path
import subprocess
import sys
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile

root = Path(__file__).resolve().parents[1]
manifest = tomllib.loads((root / 'plugin.toml').read_text())
output = Path(sys.argv[1]).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
files = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
    for name in sorted(filter(None, files)):
        path = Path(name)
        if path.parts[0] in {'prompts', 'skills', 'assets', 'fonts'} or len(path.parts) == 1 and (
                path.suffix in {'.py', '.toml', '.md'} or path.name in {'LICENSE', 'NOTICE'}):
            if path.name not in {'pyproject.toml', 'AGENTS.md'}:
                archive.write(root / path, name)
with ZipFile(output) as archive:
    instructions = manifest.get('model', {}).get('instructions')
    if instructions is not None and instructions not in archive.namelist():
        raise ValueError(f'model.instructions resource is not tracked: {instructions}')
print(output)
