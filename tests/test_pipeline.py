import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import io
import wave

spec = importlib.util.spec_from_file_location('podcast', Path(__file__).parents[1] / 'scripts' / 'podcast.py')
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)

class Engine:
    calls = 0
    fail_at = None
    def __init__(self, *a, **kw):
        pass
    def transcribe(self, path, **kw):
        Engine.calls += 1
        if Engine.calls == Engine.fail_at:
            raise RuntimeError('Simulated interruption')
        with wave.open(path) as f:
            duration = f.getnframes() / f.getframerate()
        return iter([SimpleNamespace(start=0, end=duration, text='测试内容')]), None

class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.audio = self.root / 'sample.wav'
        with wave.open(str(self.audio), 'w') as f:
            f.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            f.writeframes(b'\0\0' * 16000 * 5)
        self.args = SimpleNamespace(source=str(self.audio), out=str(self.root / 'out'), model='small', language='zh', chunk_seconds=2, preview=0, threads=1)
        Engine.calls, Engine.fail_at = 0, None
    def tearDown(self):
        self.tmp.cleanup()
    def test_resume_after_failure_and_regenerate_corrupt_chunk(self):
        Engine.fail_at = 2
        with self.assertRaises(RuntimeError):
            p.run(self.args, Engine)
        out = Path(self.args.out)
        self.assertEqual(json.loads((out/'manifest.json').read_text())['status'], 'failed')
        self.assertTrue((out/'chunks/00000.json').exists())
        self.assertFalse((out/'.run.lock').exists())
        Engine.calls, Engine.fail_at = 0, None
        m = p.run(self.args, Engine)
        self.assertEqual(Engine.calls, 2)
        self.assertEqual(m['completed_chunks'], 3)
        self.assertIn('00:00:04,000 --> 00:00:05,000', (out/'transcript.srt').read_text(encoding='utf-8'))
        p.run(self.args, Engine)
        self.assertEqual(Engine.calls, 2)
        (out/'chunks/00001.json').write_text('broken')
        p.run(self.args, Engine)
        self.assertEqual(Engine.calls, 3)
    def test_reject_changed_audio_and_settings(self):
        p.run(self.args, Engine)
        original = (Path(self.args.out)/'manifest.json').read_bytes()
        self.args.language = 'en'
        with self.assertRaises(ValueError):
            p.run(self.args, Engine)
        self.assertEqual(original, (Path(self.args.out)/'manifest.json').read_bytes())
        self.args.language = 'zh'
        with self.audio.open('ab') as f:
            f.write(b'changed')
        with self.assertRaises(ValueError):
            p.run(self.args, Engine)
        self.assertEqual(original, (Path(self.args.out)/'manifest.json').read_bytes())
    def test_lock_does_not_touch_existing_run(self):
        out = Path(self.args.out)
        out.mkdir()
        (out/'.run.lock').write_text('123')
        with self.assertRaises(FileExistsError):
            p.run(self.args, Engine)
        self.assertEqual((out/'.run.lock').read_text(), '123')
    def test_quality_flags_do_not_claim_accuracy(self):
        q = p.quality([{'start': 50, 'end': 55, 'text': '重复'}, {'start': 55, 'end': 60, 'text': '重复'}], 100, [0])
        self.assertEqual({x['kind'] for x in q['issues']}, {'empty_chunks','text_gap','tail_gap','consecutive_repeat'})
    def test_reject_non_episode_input(self):
        for url in ('https://www.xiaoyuzhoufm.com/podcast/abc', 'https://example.com/episode/abc'):
            with self.assertRaises(ValueError):
                p.source_key(url)
    def test_download_success_without_audio_is_failure(self):
        with patch.object(p, 'execute') as download:
            with self.assertRaises(RuntimeError):
                p.acquire('https://www.xiaoyuzhoufm.com/episode/abc', self.root, io.StringIO())
            self.assertEqual(download.call_count, 2)
    def test_empty_recognition_not_success(self):
        class Empty(Engine):
            def transcribe(self, *args, **kw):
                return iter([]), None
        with self.assertRaises(RuntimeError):
            p.run(self.args, Empty)
        m = json.loads((Path(self.args.out)/'manifest.json').read_text())
        self.assertEqual(m['status'], 'failed')
    def test_missing_file_does_not_create_output(self):
        self.args.source = str(self.root/'missing.wav')
        with self.assertRaises(FileNotFoundError):
            p.run(self.args, Engine)
        self.assertFalse(Path(self.args.out).exists())

if __name__ == '__main__':
    unittest.main()
