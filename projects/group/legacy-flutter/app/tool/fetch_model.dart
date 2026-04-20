import 'dart:io';

const Map<String, _ModelSpec> _specs = {
  'gemma3-1b': _ModelSpec(
    tag: 'gemma3:1b',
    gguf:
        'https://huggingface.co/bartowski/google_gemma-3-1b-it-GGUF/resolve/main/google_gemma-3-1b-it-Q4_K_M.gguf',
    fileName: 'gemma3-1b-it-q4_k_m.gguf',
    bytesHint: '~720 MB',
  ),
  'gemma3-270m': _ModelSpec(
    tag: 'gemma3:270m',
    gguf:
        'https://huggingface.co/unsloth/gemma-3-270m-it-GGUF/resolve/main/gemma-3-270m-it-Q4_K_M.gguf',
    fileName: 'gemma3-270m-it-q4_k_m.gguf',
    bytesHint: '~200 MB',
  ),
};

Future<void> main(List<String> args) async {
  final variant = args.isEmpty ? 'gemma3-1b' : args.first;
  final spec = _specs[variant];
  if (spec == null) {
    stderr.writeln('Unknown variant: $variant');
    stderr.writeln('Available: ${_specs.keys.join(", ")}');
    exit(2);
  }
  stdout.writeln('Target model: ${spec.tag} (${spec.bytesHint})');
  await _tryOllama(spec);
  await _maybeDownloadGguf(spec);
  stdout.writeln('\nDone. Start ollama (if not already): `ollama serve` and '
      'run `just run` in another shell.');
}

Future<void> _tryOllama(_ModelSpec spec) async {
  try {
    final which = await Process.run('which', ['ollama']);
    if (which.exitCode != 0) {
      stdout.writeln('\n[skip] ollama not found on PATH.');
      stdout.writeln(
          '       Install from https://ollama.com/download to use HTTP inference.');
      return;
    }
  } catch (_) {
    stdout.writeln('\n[skip] could not check ollama (non-posix env).');
    return;
  }
  stdout.writeln('\n[ollama] pulling ${spec.tag} …');
  final p = await Process.start('ollama', ['pull', spec.tag],
      mode: ProcessStartMode.inheritStdio);
  final ec = await p.exitCode;
  if (ec != 0) {
    stderr.writeln('[ollama] pull failed (exit $ec). You can retry later.');
  }
}

Future<void> _maybeDownloadGguf(_ModelSpec spec) async {
  final dir = Directory('app/assets/models');
  if (!dir.existsSync()) dir.createSync(recursive: true);
  final target = File('${dir.path}/${spec.fileName}');
  if (target.existsSync()) {
    stdout.writeln('\n[gguf] already present: ${target.path} '
        '(${_fmt(target.lengthSync())})');
    return;
  }
  stdout.writeln(
      '\n[gguf] Downloading ${spec.fileName} for future FFI use …');
  stdout.writeln('       URL: ${spec.gguf}');
  stdout.writeln('       (Skip with Ctrl-C; ollama still works without this.)');
  await Future.delayed(const Duration(seconds: 2));
  final client = HttpClient();
  try {
    final req = await client.getUrl(Uri.parse(spec.gguf));
    final res = await req.close();
    if (res.statusCode >= 400) {
      stderr.writeln(
          '[gguf] download failed: HTTP ${res.statusCode}. Skipping.');
      return;
    }
    final total = res.contentLength;
    final tmp = File('${target.path}.part');
    final sink = tmp.openWrite();
    var got = 0;
    var lastPct = -1;
    await res.forEach((chunk) {
      got += chunk.length;
      sink.add(chunk);
      if (total > 0) {
        final pct = (got * 100 / total).floor();
        if (pct != lastPct && pct % 5 == 0) {
          stdout.write('\r[gguf] $pct% (${_fmt(got)} / ${_fmt(total)})   ');
          lastPct = pct;
        }
      }
    });
    await sink.close();
    tmp.renameSync(target.path);
    stdout.writeln('\n[gguf] saved to ${target.path}');
  } catch (e) {
    stderr.writeln('[gguf] download error: $e');
  } finally {
    client.close();
  }
}

String _fmt(int bytes) {
  if (bytes >= 1 << 30) return '${(bytes / (1 << 30)).toStringAsFixed(2)} GB';
  if (bytes >= 1 << 20) return '${(bytes / (1 << 20)).toStringAsFixed(1)} MB';
  return '${(bytes / 1024).toStringAsFixed(0)} KB';
}

class _ModelSpec {
  const _ModelSpec({
    required this.tag,
    required this.gguf,
    required this.fileName,
    required this.bytesHint,
  });
  final String tag;
  final String gguf;
  final String fileName;
  final String bytesHint;
}
