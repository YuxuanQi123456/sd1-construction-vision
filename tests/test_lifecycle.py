"""Regression checks for review findings; filesystem fixtures are synthetic."""
import importlib.util
import json
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch, Mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sd1_manage', ROOT / 'scripts/manage.py')
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)


class LifecycleRegression(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sd1-lifecycle-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir()
        (self.data / 'workspace_id.json').write_text('{"workspace_id":"fixture-workspace"}')
        (self.data / 'pgdata').mkdir()
        (self.data / 'pgdata/PG_VERSION').write_text('16')
        self.state = self.root / 'state'
        self.state.mkdir()
        self.changes = patch.multiple(manage, DATA=self.data, STATE=self.state,
                                      BACKUPS=self.state / 'backups', PID_FILE=self.state / 'process.json')
        self.changes.start()
        self.addCleanup(self.changes.stop)
        self.valid = {'status':'healthy','version':'19.0.0','workspace_id':'fixture-workspace',
                      'database':'ok','frontend_dist_present':True}

    def test_reject_degraded_wrong_version_and_wrong_workspace(self):
        self.assertTrue(manage.healthy(self.valid))
        for key, value in [('status','degraded'),('version','18.0'),('workspace_id','foreign'),
                           ('database','error'),('frontend_dist_present',False)]:
            self.assertFalse(manage.healthy({**self.valid,key:value}))
        self.assertFalse(manage.healthy(None))

    def test_child_exit_never_accepted_as_healthy(self):
        with patch.object(manage,'own_process',return_value=None), patch.object(manage,'health',return_value=self.valid) as health:
            with self.assertRaises(SystemExit):
                manage.wait_ready(12345)
            health.assert_not_called()

    def test_external_database_overrides_removed(self):
        with patch.dict(os.environ, {'DATABASE_URL':'postgresql://foreign/db','DATABASE_SYNC_URL':'foreign',
                                     'OE_USE_EMBEDDED_PG':'0','DATA_DIR':'/foreign'}):
            env = manage.runtime_env()
        self.assertNotIn('DATABASE_URL',env)
        self.assertNotIn('DATABASE_SYNC_URL',env)
        self.assertEqual(env['OE_USE_EMBEDDED_PG'],'1')
        self.assertEqual(env['DATA_DIR'],str(self.data))

    def test_health_uses_explicit_no_proxy_handler(self):
        with patch.object(manage,'build_opener') as opener:
            opener.return_value.open.side_effect=OSError('synthetic network outage')
            self.assertIsNone(manage.health())
            self.assertEqual(opener.call_args.args[0].proxies,{})

    def test_backup_refuses_running_database(self):
        with patch.object(manage,'own_process',return_value=None), patch.object(manage,'pg_running',return_value=True):
            with self.assertRaises(SystemExit):
                manage.backup()
        self.assertFalse((self.state/'backups').exists())

    def test_archive_roundtrip_preserves_previous_runtime(self):
        (self.data/'fixture').write_text('before')
        with patch.object(manage,'require_stopped'):
            manage.backup()
            (self.data/'fixture').write_text('after')
            manage.restore()
        self.assertEqual((self.data/'fixture').read_text(),'before')
        previous=list(self.root.glob('data-before-restore-*'))
        self.assertEqual(len(previous),1)
        self.assertEqual((previous[0]/'fixture').read_text(),'after')
        self.assertEqual(self.data.stat().st_mode & 0o777,0o700)
        self.assertEqual((self.data/'pgdata').stat().st_mode & 0o777,0o700)

    def test_bad_backup_checksum_leaves_runtime_unchanged(self):
        with patch.object(manage,'require_stopped'):
            manage.backup()
            record=json.loads((self.state/'latest-backup.json').read_text())
            (self.state/'backups'/record['file']).write_bytes(b'corrupt')
            with self.assertRaises(SystemExit):
                manage.restore()
        self.assertTrue((self.data/'pgdata/PG_VERSION').exists())

    def test_patch_refuses_other_virtual_environment(self):
        target=self.root/'foreign-environment.py'
        target.write_text('must remain unchanged')
        dist=Mock(version='19.0.0')
        dist.locate_file.return_value=target
        with patch('importlib.metadata.distribution',return_value=dist):
            with self.assertRaises(SystemExit):
                runpy.run_path(str(ROOT/'scripts/apply_patches.py'),run_name='__main__')
        self.assertEqual(target.read_text(),'must remain unchanged')


if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(LifecycleRegression)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    output={'scope':'Review regression; synthetic filesystem fixtures, not real DB restore',
            'tests_run':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'exit_code':0 if result.wasSuccessful() else 1}
    folder=ROOT/'evidence/T04'
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'lifecycle-regression.json').write_text(json.dumps(output,indent=2)+'\n')
    raise SystemExit(output['exit_code'])
