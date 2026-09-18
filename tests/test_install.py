import importlib.util
import io
import json
import stat
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import install
import package

class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_fixed_payload_has_valid_matching_identity(self):
        self.assertEqual(len(install.source_hash(ROOT)), 64)
        m = json.loads((ROOT/'.agents/plugins/marketplace.json').read_text())
        self.assertEqual(m['plugins'][0]['name'], 'justmytype')
        self.assertEqual(m['plugins'][0]['source']['path'], './plugins/justmytype')

    def test_package_is_deterministic_and_private_free(self):
        a = package.package(ROOT, self.root/'a').read_bytes()
        b = package.package(ROOT, self.root/'b').read_bytes()
        self.assertEqual(a,b)
        with zipfile.ZipFile(io.BytesIO(a)) as z:
            self.assertEqual(set(z.namelist()), set(package.FILES))
            self.assertFalse(any('.private' in x or '.env' in x or '__pycache__' in x for x in z.namelist()))

    def test_archive_rejects_hostile_paths(self):
        for bad in ['../escape', '/escape', 'C:/escape', 'folder\\escape']:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf,'w') as z: z.writestr(bad, 'x')
            with self.subTest(path=bad), self.assertRaises(ValueError): install.extract_package(buf.getvalue(),self.root)

    def test_archive_rejects_symlink(self):
        buf=io.BytesIO()
        with zipfile.ZipFile(buf,'w') as z:
            info=zipfile.ZipInfo('link');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,'/tmp/x')
        with self.assertRaises(ValueError): install.extract_package(buf.getvalue(),self.root)

    def test_archive_extracts_complete_pack(self):
        p=package.package(ROOT,self.root/'pack')
        out=self.root/'extract';out.mkdir()
        install.extract_package(p.read_bytes(),out)
        self.assertEqual(install.source_hash(out),install.source_hash(ROOT))

    def test_missing_manifest_fails(self):
        with self.assertRaises(ValueError):install.source_hash(self.root)

    def test_trust_filters_other_plugins(self):
        class Fake:
            def call(self,*args): return {'data':[{'hooks':[{'pluginId':'other@other'}, {'pluginId':install.PLUGIN_ID}]}]}
        self.assertEqual(install.owned_hooks(Fake()),[{'pluginId':install.PLUGIN_ID}])

    def test_hook_names_and_windows_commands(self):
        h=json.loads((ROOT/'plugins/justmytype/hooks/hooks.json').read_text())['hooks']
        self.assertEqual(set(h),{'SessionStart','UserPromptSubmit','PreToolUse','PostToolUse','Stop'})
        for groups in h.values():
            handler=groups[0]['hooks'][0]
            self.assertIn('%PLUGIN_DATA%',handler['commandWindows'])
            self.assertIn('${PLUGIN_DATA}',handler['command'])
            self.assertNotIn('/home/',json.dumps(handler))

if __name__ == '__main__':unittest.main()
