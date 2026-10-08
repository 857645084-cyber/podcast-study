"""Podcast study acquisition/transcription CLI. Python 3.12, FFmpeg."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlparse

AUDIO = {'.wav', '.mp3', '.m4a', '.mp4', '.flac', '.ogg', '.aac', '.opus'}

def atomic_json(path, data):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def model_identity(model):
    p = Path(model)
    if not p.is_dir():
        return model
    return {x: digest(p / x) for x in ('model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt') if (p / x).is_file()}

def timestamp(seconds, srt=False):
    ms = round(seconds * 1000)
    h, rest = divmod(ms, 3600000)
    m, rest = divmod(rest, 60000)
    s, milli = divmod(rest, 1000)
    return f'{h:02}:{m:02}:{s:02}' + (f',{milli:03}' if srt else '')

def probe(path):
    import av
    with av.open(str(path)) as container:
        if not container.streams.audio:
            raise ValueError('No audio stream')
        stream = container.streams.audio[0]
        if container.duration is not None:
            duration = float(container.duration / av.time_base)
        elif stream.duration is not None:
            duration = float(stream.duration * stream.time_base)
        else:
            raise ValueError('Unknown audio duration')
        if not math.isfinite(duration) or duration <= 0:
            raise ValueError('Invalid audio duration')
        return duration

def execute(args, log):
    env = dict(os.environ, PYTHONIOENCODING='utf-8')
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=env)
    try:
        for line in process.stdout:
            print(line, end='', flush=True)
            log.write(line)
            log.flush()
        if process.wait():
            raise RuntimeError(f'Command failed with exit {process.returncode}')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        process.stdout.close()

def source_key(source):
    if source.startswith(('http://', 'https://')):
        u = urlparse(source)
        parts = u.path.strip('/').split('/')
        if u.hostname not in {'www.xiaoyuzhoufm.com', 'xiaoyuzhoufm.com'} or len(parts) != 2 or parts[0] != 'episode' or not parts[1].isalnum():
            raise ValueError('Use a public Xiaoyuzhou /episode/ link or a local audio file')
        return f'https://www.xiaoyuzhoufm.com/episode/{parts[1]}'
    p = Path(source).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(p)
    return str(p)

def acquire(source, out, log):
    if not source.startswith('https://'):
        return Path(source)
    folder = out / 'audio'
    folder.mkdir(exist_ok=True)
    # A previously completed and probeable file may be reused after interruption.
    for attempt in range(2):
        candidates = [p for p in folder.iterdir() if p.suffix.lower() in AUDIO and p.is_file()]
        if len(candidates) == 1:
            try:
                probe(candidates[0])
                return candidates[0]
            except Exception:
                candidates[0].rename(candidates[0].with_suffix(candidates[0].suffix + f'.invalid-{time.time_ns()}'))
        elif len(candidates) > 1:
            raise RuntimeError('More than one audio file found; choose one locally')
        cli = Path(sys.executable).with_name('casts-down.exe' if os.name == 'nt' else 'casts-down')
        try:
            execute([str(cli), source, '--output', str(folder), '--no-transcribe', '--concurrent', '1'], log)
            candidates = [p for p in folder.iterdir() if p.suffix.lower() in AUDIO and p.is_file()]
            if len(candidates) != 1:
                raise RuntimeError('Downloader produced no single audio file')
            probe(candidates[0])
            return candidates[0]
        except Exception:
            if attempt == 1:
                raise
    raise RuntimeError('Download failed')

def valid_chunk(data, index, start, end):
    try:
        if data['index'] != index or abs(data['start'] - start) > .001 or abs(data['end'] - end) > .001:
            return False
        last = start
        for s in data['segments']:
            if not isinstance(s['text'], str) or not (start <= s['start'] <= s['end'] <= end + .05) or s['start'] < last:
                return False
            last = s['start']
        return isinstance(data['segments'], list)
    except (KeyError, TypeError, ValueError):
        return False

def quality(segments, duration, empty_chunks):
    issues = []
    if not segments:
        issues.append({'kind': 'no_text', 'time': 0})
    if empty_chunks:
        issues.append({'kind': 'empty_chunks', 'indices': empty_chunks})
    last_end, previous = 0, None
    for s in segments:
        if s['start'] - last_end > 45:
            issues.append({'kind': 'text_gap', 'start': last_end, 'end': s['start']})
        if s['text'].strip() and s['text'].strip() == previous:
            issues.append({'kind': 'consecutive_repeat', 'time': s['start']})
        previous = s['text'].strip()
        last_end = max(last_end, s['end'])
    if duration - last_end > 30:
        issues.append({'kind': 'tail_gap', 'start': last_end, 'end': duration})
    return {'issues': issues, 'last_text_end': last_end, 'processed_audio_seconds': duration,
            'notice': 'Heuristics only. Silence/music can cause gaps; no flags does not prove accuracy. Chunk boundaries require spot checks.'}

def export(out, segments):
    txt = '\n'.join(f"[{timestamp(s['start'])}] {s['text']}" for s in segments) + '\n'
    srt = '\n\n'.join(f"{i}\n{timestamp(s['start'], True)} --> {timestamp(s['end'], True)}\n{s['text']}" for i, s in enumerate(segments, 1)) + '\n'
    for name, content in [('transcript.txt', txt), ('transcript.srt', srt)]:
        tmp = out / (name + '.tmp')
        tmp.write_text(content, encoding='utf-8')
        os.replace(tmp, out / name)

def record(out, m):
    text = f"""# 处理记录

- 状态：{m.get('status')}
- 来源：{m.get('source')}
- 模式：{m.get('mode')}（preview 仅为节选）
- 原音频时长：{m.get('audio_seconds', '未知')} 秒
- 本次处理范围：{m.get('target_seconds', '未知')} 秒
- 模型：{m.get('settings', {}).get('model', '未知')}
- 完成段数：{m.get('completed_chunks', 0)} / {m.get('total_chunks', '未知')}
- 本次耗时：{m.get('elapsed_seconds', '未知')} 秒
- 错误：{m.get('error', '无')}

尚未逐句人工核听。quality.json 是自动疑点检查，不能证明准确。
分段边界可能截断句子；按时间戳抽查。没有自动区分说话人。
学习笔记由 Agent 通读材料后另行生成，转写脚本不会自动调用云端语言模型。
"""
    (out / '处理记录.md').write_text(text, encoding='utf-8')

def run(args, factory=None):
    source = source_key(args.source)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    settings = {'model': args.model, 'model_identity': model_identity(args.model), 'language': args.language, 'chunk_seconds': args.chunk_seconds, 'preview': args.preview, 'compute_type': 'int8', 'engine_version': importlib.metadata.version('faster-whisper')}
    lock = out / '.run.lock'
    fd = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    manifest = out / 'manifest.json'
    m, accepted = {}, False
    started = time.monotonic()
    try:
        if manifest.exists():
            m = json.loads(manifest.read_text(encoding='utf-8'))
            if m['source'] != source or m['settings'] != settings:
                raise ValueError('Source/settings changed: use a new output directory')
        else:
            if any((out / p).exists() for p in ('chunks', 'transcript.txt', 'transcript.srt')):
                raise ValueError('Output contains artifacts without a manifest: use a new directory')
            m = {'source': source, 'settings': settings, 'mode': 'preview' if args.preview else 'full'}
        accepted = True
        with (out / 'run.log').open('a', encoding='utf-8') as log:
            audio = acquire(source, out, log)
            fingerprint = digest(audio)
            if 'audio_sha256' in m and m['audio_sha256'] != fingerprint:
                accepted = False
                raise ValueError('Audio changed: use a new output directory')
            duration = probe(audio)
            target = min(duration, args.preview) if args.preview else duration
            count = math.ceil(target / args.chunk_seconds)
            m.update(audio_sha256=fingerprint, audio_file=str(audio), audio_seconds=duration, target_seconds=target, total_chunks=count, status='transcribing', completed_chunks=0)
            m.pop('error', None)
            atomic_json(manifest, m)
            folder = out / 'chunks'
            folder.mkdir(exist_ok=True)
            engine, all_segments, empty = None, [], []
            for index in range(count):
                start, end = index * args.chunk_seconds, min((index + 1) * args.chunk_seconds, target)
                path = folder / f'{index:05}.json'
                data = None
                if path.exists():
                    try:
                        data = json.loads(path.read_text(encoding='utf-8'))
                    except (ValueError, OSError):
                        pass
                if not data or not valid_chunk(data, index, start, end):
                    if engine is None:
                        if factory is None:
                            from faster_whisper import WhisperModel
                            factory = WhisperModel
                        engine = factory(args.model, device='cpu', compute_type='int8', cpu_threads=args.threads)
                    wav = folder / f'{index:05}.wav'
                    execute(['ffmpeg', '-hide_banner', '-loglevel', 'error', '-y', '-ss', str(start), '-i', str(audio), '-t', str(end - start), '-vn', '-ar', '16000', '-ac', '1', str(wav)], log)
                    try:
                        items, _ = engine.transcribe(str(wav), language=None if args.language == 'auto' else args.language, vad_filter=True, beam_size=5)
                        segments = [{'start': round(start + max(0, min(float(s.start), end-start)), 3), 'end': round(start + max(0, min(float(s.end), end-start)), 3), 'text': s.text.strip()} for s in items if s.text.strip()]
                        data = {'index': index, 'start': start, 'end': end, 'segments': segments}
                        if not valid_chunk(data, index, start, end):
                            raise ValueError('Invalid segment timestamps')
                        atomic_json(path, data)
                    finally:
                        wav.unlink(missing_ok=True)
                all_segments.extend(data['segments'])
                if not data['segments']:
                    empty.append(index)
                m['completed_chunks'] = index + 1
                atomic_json(manifest, m)
                msg = f'Chunk {index + 1}/{count} saved; audio {timestamp(end)} / {timestamp(target)}'
                print(msg, flush=True)
                log.write(msg + '\n')
                log.flush()
            q = quality(all_segments, target, empty)
            q['chunk_boundaries_to_review'] = [i * args.chunk_seconds for i in range(1, count)]
            export(out, all_segments)
            atomic_json(out / 'quality.json', q)
            m['status'] = 'needs_review' if q['issues'] else 'complete'
            if not all_segments:
                raise RuntimeError('No speech text produced; inspect audio and quality report')
    except BaseException as exc:
        if accepted:
            m.update(status='interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=f'{type(exc).__name__}: {exc}')
        raise
    finally:
        if accepted:
            m['elapsed_seconds'] = round(time.monotonic() - started, 2)
            atomic_json(manifest, m)
            record(out, m)
        lock.unlink(missing_ok=True)
    return m

def doctor():
    data = {'python': sys.version.split()[0], 'ffmpeg': shutil.which('ffmpeg'), 'packages': {}}
    for package in ('faster-whisper', 'av', 'casts-down'):
        try:
            data['packages'][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            data['packages'][package] = None
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0 if data['ffmpeg'] and all(data['packages'].values()) else 1

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor')
    p = sub.add_parser('run')
    p.add_argument('source')
    p.add_argument('--out', required=True)
    p.add_argument('--model', default='small')
    p.add_argument('--language', default='zh')
    p.add_argument('--chunk-seconds', type=int, default=180)
    p.add_argument('--preview', type=int, default=0)
    p.add_argument('--threads', type=int, default=min(8, os.cpu_count() or 4))
    args = parser.parse_args()
    if args.command == 'doctor':
        return doctor()
    if args.chunk_seconds < 1 or args.preview < 0 or args.threads < 1:
        parser.error('Durations/threads must be positive; preview=0 means full')
    try:
        result = run(args)
        print(f"Finished: {result['status']}; output: {Path(args.out).resolve()}")
        return 0
    except KeyboardInterrupt:
        print('Interrupted. Run the same command to resume.', file=sys.stderr)
        return 130
    except Exception as exc:
        print(f'{type(exc).__name__}: {exc}', file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
