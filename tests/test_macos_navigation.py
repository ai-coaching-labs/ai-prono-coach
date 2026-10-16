"""Régression : le port choisi reste dans la fenêtre intégrée."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform == 'darwin' and shutil.which('swift'), 'Swift macOS requis')
class MacOSNavigationTests(unittest.TestCase):
    def test_dashboard_origin_with_dynamic_port(self):
        source = (ROOT / 'macos/PronoCoach.swift').read_text()
        function = source[source.index('func isDashboardNavigation('):source.index('// Réserver un port libre')]
        checks = '''
let origin = URL(string: "http://127.0.0.1:53124/")!
for path in ["/", "/?tab=tracking", "/chat", "/chat?league=UCL", "/api/health"] {
    precondition(isDashboardNavigation(URL(string: path, relativeTo: origin)!.absoluteURL, dashboardURL: origin))
}
for address in ["http://127.0.0.1:8877/", "http://127.0.0.1:53125/", "https://127.0.0.1:53124/", "http://example.com:53124/", "http://user@127.0.0.1:53124/"] {
    precondition(!isDashboardNavigation(URL(string: address)!, dashboardURL: origin))
}
'''
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'navigation.swift'
            script.write_text('import Foundation\n' + function + checks)
            result = subprocess.run(['swift', str(script)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
