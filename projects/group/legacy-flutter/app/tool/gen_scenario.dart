import 'dart:convert';
import 'dart:io';

Future<void> main(List<String> args) async {
  if (args.isEmpty) {
    stderr.writeln('Usage: gen_scenario "<short description of scam>"');
    exit(2);
  }
  final desc = args.join(' ');
  final slug = desc
      .toLowerCase()
      .replaceAll(RegExp(r'[^a-z0-9]+'), '_')
      .replaceAll(RegExp(r'^_+|_+$'), '');
  final useOpenAi = Platform.environment.containsKey('OPENAI_API_KEY');
  final payload = useOpenAi
      ? await _genWithOpenAi(desc)
      : await _genWithOllama(desc);
  final target = File(
      '../scenarios/${DateTime.now().millisecondsSinceEpoch}_$slug.json');
  payload['id'] = '${DateTime.now().millisecondsSinceEpoch}_$slug';
  target.writeAsStringSync(
      const JsonEncoder.withIndent('  ').convert(payload));
  stdout.writeln('Wrote ${target.path}');
  stdout.writeln('Run `just sync-scenarios` to register it.');
}

const String _systemPrompt = '''
You generate realistic anti-scam test scenarios for the Guardian prototype.
Return STRICT JSON (no prose). Schema:
{
  "id": "slug",
  "label": "short label",
  "category": "sms_phishing|voice_call|chat_scam|multi_vector|benign",
  "expected": {"intervention": "none|banner|full_screen|full_screen_delay",
                "min_risk": <number>, "max_risk": <number>},
  "events": [
    {"t_seconds": 0, "type": "sms|call|chat|transaction_attempt", ...}
  ]
}
SMS payload: from, body.
Call payload: from, direction, duration_seconds, transcript.
Chat payload: contact, direction, body.
Transaction payload: amount_hkd, to_name, to_account, new_recipient, channel.
Events must be temporally ordered and realistic. Use HK context (HKD, HK Police, FPS).
''';

Future<Map<String, dynamic>> _genWithOllama(String desc) async {
  final client = HttpClient();
  try {
    final req = await client.postUrl(
        Uri.parse('http://localhost:11434/api/chat'));
    req.headers.contentType = ContentType.json;
    req.write(jsonEncode({
      'model': 'gemma3:1b',
      'messages': [
        {'role': 'system', 'content': _systemPrompt},
        {'role': 'user', 'content': desc},
      ],
      'stream': false,
      'format': 'json',
      'options': {'temperature': 0.6},
    }));
    final res = await req.close();
    final body = await res.transform(utf8.decoder).join();
    final decoded = jsonDecode(body) as Map<String, dynamic>;
    final content = decoded['message']['content'] as String;
    return jsonDecode(content) as Map<String, dynamic>;
  } finally {
    client.close();
  }
}

Future<Map<String, dynamic>> _genWithOpenAi(String desc) async {
  final key = Platform.environment['OPENAI_API_KEY']!;
  final client = HttpClient();
  try {
    final req = await client.postUrl(
        Uri.parse('https://api.openai.com/v1/chat/completions'));
    req.headers.contentType = ContentType.json;
    req.headers.set('Authorization', 'Bearer $key');
    req.write(jsonEncode({
      'model': 'gpt-4o-mini',
      'response_format': {'type': 'json_object'},
      'temperature': 0.5,
      'messages': [
        {'role': 'system', 'content': _systemPrompt},
        {'role': 'user', 'content': desc},
      ],
    }));
    final res = await req.close();
    final body = await res.transform(utf8.decoder).join();
    final decoded = jsonDecode(body) as Map<String, dynamic>;
    final content =
        decoded['choices'][0]['message']['content'] as String;
    return jsonDecode(content) as Map<String, dynamic>;
  } finally {
    client.close();
  }
}
