"""Detached transcription and bounded local lookup. No LLM calls."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import podcast


def alive(pid):
    if os.name == 'nt':
        from ctypes import wintypes
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenProcess.restype = wintypes.HANDLE
        api.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = api.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 5:
                raise PermissionError('Cannot inspect process; do not assume it stopped')
            return False
        try:
            code = wintypes.DWORD()
            if not api.GetExitCodeProcess(handle, ctypes.byref(code)):
                raise OSError('Cannot inspect process')
            return code.value == 259
        finally:
            api.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def start(args):
    source = podcast.source_key(args.source)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    lock = out / '.launch.lock'
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    os.close(fd)
    try:
        if (out/'job.json').exists():
            old = json.loads((out/'job.json').read_text(encoding='utf-8'))
            if alive(old['pid']):
                raise RuntimeError('Existing job is running; use status')
        if (out/'.run.lock').exists():
            raise RuntimeError('Run lock exists; verify its process before recovery')
        command = [sys.executable, '-u', str(Path(__file__).with_name('podcast.py')),
                   'run', source, '--out', str(out), '--model', args.model,
                   '--language', args.language, '--preview', str(args.preview),
                   '--chunk-seconds', str(args.chunk_seconds), '--threads', str(args.threads)]
        options = {'creationflags': subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        with (out/'background.log').open('a', encoding='utf-8') as log:
            child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=log,
                                     stderr=subprocess.STDOUT, close_fds=True,
                                     env=dict(os.environ, PYTHONIOENCODING='utf-8'), **options)
        job = {'pid': child.pid, 'source': source, 'started_at': time.time(), 'out': str(out)}
        podcast.atomic_json(out/'job.json', job)
        return dict(job, notice='Launched only; use status later. No automatic AI notes or notification.')
    finally:
        lock.unlink(missing_ok=True)


def status(out):
    out = Path(out)
    job = json.loads((out/'job.json').read_text(encoding='utf-8')) if (out/'job.json').exists() else None
    m = json.loads((out/'manifest.json').read_text(encoding='utf-8')) if (out/'manifest.json').exists() else {}
    pid = job['pid'] if job else None
    if not pid and (out/'.run.lock').exists():
        pid = int((out/'.run.lock').read_text())
    running = alive(pid) if pid else False
    state = m.get('status', 'starting' if running else 'not_started')
    if job and (out/'manifest.json').exists() and (out/'manifest.json').stat().st_mtime < job.get('started_at', 0):
        state = 'starting' if running else 'stopped_before_manifest'
    if not running and state in ('transcribing', 'starting'):
        state = 'stopped_incomplete'
    if job and not running and not m:
        state = 'stopped_before_manifest'
    return {'state': state, 'running': running, 'pid': pid,
            'completed_chunks': m.get('completed_chunks', 0), 'total_chunks': m.get('total_chunks'),
            'mode': m.get('mode'), 'target_seconds': m.get('target_seconds'),
            'error': m.get('error'), 'notes_exist': (out/'学习笔记.md').exists(),
            'log': str(out/'background.log')}


def seconds(value):
    if not re.fullmatch(r'\d+:\d{2}:\d{2}', value):
        raise ValueError('Use HH:MM:SS')
    h, m, s = map(int, value.split(':'))
    if m > 59 or s > 59:
        raise ValueError('Invalid time')
    return h*3600+m*60+s


def transcript(out):
    path = Path(out)/'transcript.txt'
    if not path.is_file():
        raise FileNotFoundError('Completed transcript.txt not found; check status')
    rows = []
    for line in path.read_text(encoding='utf-8').splitlines():
        match = re.match(r'\[(\d+:\d{2}:\d{2})\]\s*(.*)', line)
        if match:
            rows.append((seconds(match[1]), line))
    if not rows:
        raise ValueError('No timestamped text')
    return rows


def search(args):
    matches = [line[:260] for _, line in transcript(args.out) if args.query.casefold() in line.casefold()]
    return {'query': args.query, 'total_matches': len(matches), 'matches': matches[:args.limit],
            'notice': 'Local matches, not chapter titles or verified quotations.'}


def extract(args):
    begin, end = seconds(args.start), seconds(args.end)
    if begin >= end:
        raise ValueError('Start must precede end')
    rows = transcript(args.out)
    selected = []
    for i, (t, line) in enumerate(rows):
        next_t = rows[i+1][0] if i+1 < len(rows) else t+1
        if t < end and next_t > begin:
            selected.append(line)
    body = '\n'.join(selected)
    if not body:
        raise ValueError('No text in requested range')
    if len(body) > args.max_chars:
        raise ValueError(f'Range has {len(body)} characters, limit {args.max_chars}; narrow range or explicitly raise --max-chars')
    dest = Path(args.dest).resolve()
    protected = {'transcript.txt', 'transcript.srt', 'manifest.json', 'quality.json', 'job.json', '学习笔记.md'}
    if dest.name in protected or dest.suffix.lower() not in {'.txt', '.md'}:
        raise ValueError('Use a separate .txt/.md excerpt destination')
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(f'选段：{args.start}—{args.end}；边界按TXT时间戳近似，未核听。\n\n'+body+'\n', encoding='utf-8')
    return {'path': str(dest), 'characters': len(body), 'lines': len(selected), 'range': [args.start, args.end]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('start')
    p.add_argument('source')
    p.add_argument('--out', required=True)
    p.add_argument('--model', default='small')
    p.add_argument('--language', default='zh')
    p.add_argument('--preview', type=int, default=0)
    p.add_argument('--chunk-seconds', type=int, default=180)
    p.add_argument('--threads', type=int, default=min(8, os.cpu_count() or 4))
    p = sub.add_parser('status')
    p.add_argument('--out', required=True)
    p = sub.add_parser('search')
    p.add_argument('--out', required=True)
    p.add_argument('--query', required=True)
    p.add_argument('--limit', type=int, default=12)
    p = sub.add_parser('extract')
    p.add_argument('--out', required=True)
    p.add_argument('--start', required=True)
    p.add_argument('--end', required=True)
    p.add_argument('--dest', required=True)
    p.add_argument('--max-chars', type=int, default=20000)
    args = parser.parse_args()
    try:
        if args.command == 'start' and (args.preview < 0 or args.chunk_seconds < 1 or args.threads < 1):
            raise ValueError('Invalid duration/threads')
        if args.command == 'search' and (not args.query.strip() or not 1 <= args.limit <= 50):
            raise ValueError('Use a nonempty query and limit 1..50')
        if args.command == 'extract' and args.max_chars < 1:
            raise ValueError('Character limit must be positive')
        result = status(args.out) if args.command == 'status' else globals()[args.command](args)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
