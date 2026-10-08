"""Build a source-only release ZIP. Does not publish or upload anything."""
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FILES = ['SKILL.md', 'README.md', 'DESIGN.md', 'VALIDATION.md', 'LICENSE', 'THIRD_PARTY.md', 'requirements.txt', '.gitignore', 'agents/openai.yaml', 'references/learning-notes.md', 'scripts/podcast.py', 'scripts/package_release.py', 'tests/test_pipeline.py']

if __name__ == '__main__':
    destination = ROOT / 'dist' / 'podcast-study-v0.1.zip'
    destination.parent.mkdir(exist_ok=True)
    for name in FILES:
        if not (ROOT/name).is_file():
            raise FileNotFoundError(name)
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in FILES:
            archive.write(ROOT/name, 'podcast-study/' + name)
    print(destination)
