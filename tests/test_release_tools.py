"""Release guards reject inconsistent versions and private or stale bundle content."""
import hashlib
import importlib.util
import io
from pathlib import Path
import plistlib
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / '.github/scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


version_tool = load_script('check_version')
with patch.dict(sys.modules, {'check_version': version_tool}):
    macos_tool = load_script('verify_macos')


class ReleaseToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.files = {
            'pyproject.toml': '[project]\nversion = "1.2.3"\n',
            'src/prono/__init__.py': '__version__ = "1.2.3"\n',
            'src/prono/assets/chat.html': '<main>Example</main>',
            'src/prono/assets/chat.js': 'console.log("example");',
            'src/prono/assets/chat.css': 'main { color: black; }',
            'AGENTS.md': 'Shared instructions', 'README.md': 'Example', 'LICENSE': 'MIT License',
            'agents/coach.md': 'Example coach', 'config/workspace.toml': '[agents]\n',
        }
        for name, content in self.files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        self.app = self.root / 'Example.app'
        (self.app / 'Contents/Resources').mkdir(parents=True)

    def bundle(self, extra=None, changed=None):
        files = {**self.files, **(extra or {}), **(changed or {})}
        archive = self.app / 'Contents/Resources/engine.tar.gz'
        with tarfile.open(archive, 'w:gz') as bundle:
            for name, text in files.items():
                data = text.encode()
                info = tarfile.TarInfo('./' + name)
                info.size = len(data)
                bundle.addfile(info, io.BytesIO(data))
        info = {'CFBundleShortVersionString': '1.2.3',
                'PronoEngineBuild': hashlib.sha256(archive.read_bytes()).hexdigest()}
        with (self.app / 'Contents/Info.plist').open('wb') as output:
            plistlib.dump(info, output)

    def test_matching_versions_and_tag(self):
        self.assertEqual(version_tool.project_version(self.root, 'v1.2.3'), '1.2.3')
        for tag in ('v1.2.4', '1.2.3', 'v1.2.3-rc1', ''):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                version_tool.project_version(self.root, tag)

    def test_conflicting_or_prerelease_project_versions_are_rejected(self):
        (self.root / 'src/prono/__init__.py').write_text('__version__ = "9.9.9"')
        with self.assertRaisesRegex(ValueError, 'même version'):
            version_tool.project_version(self.root)
        (self.root / 'pyproject.toml').write_text('[project]\nversion = "1.2.3rc1"')
        with self.assertRaisesRegex(ValueError, 'stable'):
            version_tool.project_version(self.root)

    def test_valid_bundle_and_resources(self):
        self.bundle()
        macos_tool.verify_app(self.root, self.app)

    def test_private_paths_and_stale_resources_are_rejected(self):
        for path in ('data/history.csv', 'config/workspace.user.toml', '../secret', '/secret'):
            with self.subTest(path=path):
                self.bundle(extra={path: 'Private'})
                with self.assertRaises(ValueError):
                    macos_tool.verify_app(self.root, self.app)
        self.bundle(changed={'src/prono/assets/chat.js': 'stale'})
        with self.assertRaisesRegex(ValueError, 'Ressource'):
            macos_tool.verify_app(self.root, self.app)
        self.bundle(changed={'LICENSE': 'stale license'})
        with self.assertRaisesRegex(ValueError, 'Ressource'):
            macos_tool.verify_app(self.root, self.app)

    def test_tampered_archive_is_rejected(self):
        self.bundle()
        archive = self.app / 'Contents/Resources/engine.tar.gz'
        archive.write_bytes(archive.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'empreinte'):
            macos_tool.verify_app(self.root, self.app)
