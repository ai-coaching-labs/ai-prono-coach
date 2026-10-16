"""Une mise à jour du moteur conserve les personnalisations et un retour arrière."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prono_install', ROOT / 'scripts/install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)


class InstallMCPTests(unittest.TestCase):
    def test_generated_config_migrates_preserving_other_servers_and_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = root / 'engine-old'
            (old / 'src/prono').mkdir(parents=True)
            (old / 'src/prono/cli.py').touch()
            entry = {'command': str(old / '.venv/bin/python'),
                     'args': ['-m', 'prono.cli', '--workspace', str(root), 'mcp']}
            config = {'mcpServers': {'prono': entry, 'other': {'command': 'custom'}}}
            path = root / '.mcp.json'
            original = json.dumps(config)
            path.write_text(original)
            new = root / 'engine-new/.venv/bin/python'
            (root / 'engine-new/src/prono').mkdir(parents=True)
            (root / 'engine-new/src/prono/cli.py').touch()
            installer.install_mcp(root, new)
            actual = json.loads(path.read_text())
            self.assertEqual(actual['mcpServers']['prono']['command'], str(new))
            self.assertEqual(actual['mcpServers']['other'], {'command': 'custom'})
            self.assertEqual((root / '.mcp.json.before-engine-update').read_text(), original)
            installer.install_mcp(root, new)
            self.assertEqual(len(list(root.glob('.mcp.json.before-engine-update*'))), 1)

    def test_custom_and_invalid_config_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / '.mcp.json'
            for content in ['invalid json', '[]', json.dumps({'mcpServers': {'prono': {
                'command': '/custom/python', 'args': [], 'env': {'CUSTOM': 'value'}}}})]:
                with self.subTest(content=content):
                    path.write_text(content)
                    installer.install_mcp(root, root / '.venv/bin/python')
                    self.assertEqual(path.read_text(), content)
                    self.assertFalse((root / '.mcp.json.before-engine-update').exists())
