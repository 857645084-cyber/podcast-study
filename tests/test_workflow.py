import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).parents[1]/'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('workflow', SCRIPTS/'workflow.py')
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'transcript.txt').write_text('[00:00:00] 开场\n[00:00:10] 顶层目标\n[00:00:20] 后续\n', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_search_is_bounded_and_preserves_times(self):
        result = w.search(SimpleNamespace(out=self.root, query='目标', limit=1))
        self.assertEqual(result['matches'], ['[00:00:10] 顶层目标'])

    def test_range_includes_boundary_segment_and_rejects_over_budget(self):
        args = SimpleNamespace(out=self.root, start='00:00:12', end='00:00:20', max_chars=100, dest=self.root/'选段.txt')
        w.extract(args)
        text = args.dest.read_text(encoding='utf-8')
        self.assertIn('顶层目标', text)
        self.assertNotIn('后续', text)
        args.dest = self.root/'超限.txt'
        args.max_chars = 1
        with self.assertRaises(ValueError):
            w.extract(args)
        self.assertFalse(args.dest.exists())

    def test_extraction_cannot_overwrite_original(self):
        args = SimpleNamespace(out=self.root, start='00:00:00', end='00:00:20', max_chars=100, dest=self.root/'transcript.txt')
        original = args.dest.read_bytes()
        with self.assertRaises(ValueError):
            w.extract(args)
        self.assertEqual(original, args.dest.read_bytes())

    def test_dead_job_is_not_reported_as_transcribing_or_complete(self):
        (self.root/'job.json').write_text(json.dumps({'pid': 123}))
        (self.root/'manifest.json').write_text(json.dumps({'status':'transcribing', 'completed_chunks':2, 'total_chunks':5}))
        with patch.object(w, 'alive', return_value=False):
            self.assertEqual(w.status(self.root)['state'], 'stopped_incomplete')

    def test_start_rejects_existing_live_job(self):
        (self.root/'job.json').write_text(json.dumps({'pid': 123}))
        args = SimpleNamespace(source=str(self.root/'transcript.txt'), out=self.root)
        with patch.object(w, 'alive', return_value=True), patch.object(w.subprocess, 'Popen') as launch:
            with self.assertRaises(RuntimeError):
                w.start(args)
            launch.assert_not_called()
        self.assertFalse((self.root/'.launch.lock').exists())


if __name__ == '__main__':
    unittest.main()
