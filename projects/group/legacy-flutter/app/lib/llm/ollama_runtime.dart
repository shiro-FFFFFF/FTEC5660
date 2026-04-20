import 'dart:convert';
import 'dart:developer' as dev;

import 'package:http/http.dart' as http;

import '../agents/context_agent.dart';
import '../agents/risk_agent.dart';
import 'llm_runtime.dart';
import 'prompts.dart';
import 'tools.dart';

class OllamaLlmRuntime implements LlmRuntime {
  OllamaLlmRuntime({
    this.model = 'llama3.2:3b',
    Uri? endpoint,
    http.Client? client,
  })  : endpoint = endpoint ?? Uri.parse('http://localhost:11434'),
        _client = client ?? http.Client();

  final String model;
  final Uri endpoint;
  final http.Client _client;
  bool _warm = false;

  @override
  bool get ready => _warm;

  @override
  String get name => 'ollama/$model';

  Future<bool> isReachable({
    Duration timeout = const Duration(seconds: 2),
  }) async {
    try {
      final r = await _client
          .get(endpoint.resolve('/api/tags'))
          .timeout(timeout);
      if (r.statusCode != 200) return false;
      final body = jsonDecode(r.body) as Map<String, dynamic>;
      final models = (body['models'] as List? ?? const [])
          .whereType<Map<String, dynamic>>()
          .map((m) => m['name'] as String? ?? '')
          .toList();
      return models.any((m) => m.startsWith(model.split(':').first));
    } catch (e) {
      dev.log('ollama not reachable: $e', name: 'llm');
      return false;
    }
  }

  @override
  Future<void> warmup() async {
    if (_warm) return;
    try {
      await _chat(
        messages: [
          {'role': 'system', 'content': 'You are a JSON-only assistant.'},
          {'role': 'user', 'content': 'Reply with {"ok": true}'},
        ],
        timeout: const Duration(seconds: 45),
      );
      _warm = true;
      dev.log('ollama warmed up: $model', name: 'llm');
    } catch (e) {
      dev.log('ollama warmup failed: $e', name: 'llm');
    }
  }

  @override
  Future<LlmRiskOutput> scoreRisk({
    required ContextSnapshot snapshot,
    required double ruleScore,
    required List<RuleScoreContribution> ruleContributions,
    ToolRegistry? tools,
  }) async {
    if (tools != null) {
      return _scoreRiskReact(
        snapshot: snapshot,
        ruleScore: ruleScore,
        ruleContributions: ruleContributions,
        tools: tools,
      );
    }
    return _scoreRiskSingleShot(
      snapshot: snapshot,
      ruleScore: ruleScore,
      ruleContributions: ruleContributions,
    );
  }

  Future<LlmRiskOutput> _scoreRiskSingleShot({
    required ContextSnapshot snapshot,
    required double ruleScore,
    required List<RuleScoreContribution> ruleContributions,
  }) async {
    final prompt = buildRiskPrompt(
      snapshot: snapshot,
      ruleScore: ruleScore,
      ruleContributions: ruleContributions,
    );
    Map<String, dynamic>? parsed;
    for (var attempt = 0; attempt < 2 && parsed == null; attempt++) {
      try {
        final content = await _chat(
          messages: [
            {'role': 'system', 'content': riskSystemPrompt},
            {'role': 'user', 'content': prompt},
          ],
          json: true,
          timeout: const Duration(seconds: 30),
        );
        parsed = _extractJson(content);
      } catch (e) {
        dev.log('ollama scoreRisk attempt $attempt failed: $e', name: 'llm');
      }
    }
    if (parsed == null) {
      throw StateError('Ollama failed to return valid JSON');
    }
    return _buildOutput(parsed, ruleScore, trace: const []);
  }

  /// Multi-turn ReAct loop. The model emits `<tool>{...}</tool>` to call a
  /// tool or `<final>{...}</final>` to commit a verdict. We run up to
  /// [maxSteps] tool calls; after that we force a final answer. The entire
  /// tool-call trace is returned alongside the verdict so the audit UI can
  /// show every step.
  Future<LlmRiskOutput> _scoreRiskReact({
    required ContextSnapshot snapshot,
    required double ruleScore,
    required List<RuleScoreContribution> ruleContributions,
    required ToolRegistry tools,
    int maxSteps = 4,
  }) async {
    final system = buildReactSystemPrompt(tools);
    final userPrompt = buildRiskPrompt(
      snapshot: snapshot,
      ruleScore: ruleScore,
      ruleContributions: ruleContributions,
    );
    final messages = <Map<String, String>>[
      {'role': 'system', 'content': system},
      {'role': 'user', 'content': userPrompt},
    ];

    final trace = <ToolCallStep>[];
    Map<String, dynamic>? finalJson;
    String? lastContent;

    for (var step = 0; step < maxSteps + 1 && finalJson == null; step++) {
      // On the last allowed step, force a final answer.
      if (step == maxSteps) {
        messages.add({
          'role': 'user',
          'content': 'You have reached the tool-call budget. '
              'Emit <final>{...}</final> now with your best verdict.',
        });
      }

      String content;
      try {
        content = await _chat(
          messages: messages,
          timeout: const Duration(seconds: 30),
        );
      } catch (e) {
        dev.log('ollama ReAct step $step chat failed: $e', name: 'llm');
        break;
      }
      lastContent = content;

      final parsed = _parseReactTurn(content);
      if (parsed is _FinalAnswer) {
        finalJson = parsed.json;
        break;
      }
      if (parsed is _ToolCall) {
        final tool = tools.find(parsed.name);
        if (tool == null) {
          dev.log('[react] step $step: unknown tool "${parsed.name}"',
              name: 'llm');
          messages.add({'role': 'assistant', 'content': content});
          messages.add({
            'role': 'user',
            'content':
                '<observation>{"error": "unknown tool: ${parsed.name}"}</observation>',
          });
          continue;
        }
        final started = DateTime.now();
        Map<String, dynamic> result;
        try {
          result = await tool.call(parsed.args);
        } catch (e) {
          result = {'error': e.toString()};
        }
        final ms = DateTime.now().difference(started).inMilliseconds;
        trace.add(ToolCallStep(
          tool: parsed.name,
          args: parsed.args,
          result: result,
          latencyMs: ms,
        ));
        dev.log(
          '[react] step $step → ${parsed.name}(${jsonEncode(parsed.args)}) '
          '→ ${jsonEncode(result)} (${ms}ms)',
          name: 'llm',
        );
        messages.add({'role': 'assistant', 'content': content});
        messages.add({
          'role': 'user',
          'content': '<observation>${jsonEncode(result)}</observation>',
        });
        continue;
      }
      // Model emitted neither tag — try to salvage a JSON verdict, else nudge.
      final salvage = _extractJson(content);
      if (salvage != null) {
        finalJson = salvage;
        break;
      }
      messages.add({'role': 'assistant', 'content': content});
      messages.add({
        'role': 'user',
        'content': 'Invalid format. Respond ONLY with <tool>...</tool> or '
            '<final>...</final>.',
      });
    }

    if (finalJson == null && lastContent != null) {
      finalJson = _extractJson(lastContent);
    }
    if (finalJson == null) {
      throw StateError('Ollama ReAct loop did not converge on a final answer');
    }
    return _buildOutput(finalJson, ruleScore, trace: trace);
  }

  LlmRiskOutput _buildOutput(
    Map<String, dynamic> parsed,
    double ruleScore, {
    required List<ToolCallStep> trace,
  }) {
    final risk =
        ((parsed['risk'] as num?) ?? ruleScore).toDouble().clamp(0.0, 1.0);
    final tactics = (parsed['tactics'] as List?)
            ?.whereType<String>()
            .toList() ??
        const <String>[];
    final reasons = (parsed['reasons'] as List?)
            ?.whereType<String>()
            .toList() ??
        const <String>[];
    final conf = ((parsed['confidence'] as num?) ?? 0.5)
        .toDouble()
        .clamp(0.0, 1.0);
    return LlmRiskOutput(
      risk: risk,
      tactics: tactics,
      reasons: reasons,
      confidence: conf,
      source: trace.isEmpty ? name : '$name+react',
      trace: trace,
    );
  }

  @override
  Future<String> explain({
    required ContextSnapshot snapshot,
    required double finalRisk,
  }) async {
    final user =
        'Summarise in one short plain-language sentence (max 18 words) why '
        'the following situation has a risk of ${(finalRisk * 100).toStringAsFixed(0)}%. '
        'Be gentle and elderly-friendly. Do not use technical jargon.\n\n'
        '${buildRiskPrompt(snapshot: snapshot, ruleScore: finalRisk, ruleContributions: const [])}';
    final content = await _chat(
      messages: [
        {
          'role': 'system',
          'content':
              'You write one short, kind, plain-language sentence for an '
                  'elderly banking user. No preface, no markdown.',
        },
        {'role': 'user', 'content': user},
      ],
      timeout: const Duration(seconds: 20),
    );
    return content.trim();
  }

  Future<String> _chat({
    required List<Map<String, String>> messages,
    bool json = false,
    Duration timeout = const Duration(seconds: 30),
  }) async {
    final body = {
      'model': model,
      'messages': messages,
      'stream': false,
      if (json) 'format': 'json',
      'options': {'temperature': 0.1, 'num_ctx': 2048},
    };
    final r = await _client
        .post(
          endpoint.resolve('/api/chat'),
          headers: const {'Content-Type': 'application/json'},
          body: jsonEncode(body),
        )
        .timeout(timeout);
    if (r.statusCode != 200) {
      throw StateError('ollama http ${r.statusCode}: ${r.body}');
    }
    final decoded = jsonDecode(r.body) as Map<String, dynamic>;
    final msg = decoded['message'] as Map<String, dynamic>?;
    return (msg?['content'] as String?) ?? '';
  }

  Map<String, dynamic>? _extractJson(String raw) {
    try {
      return jsonDecode(raw) as Map<String, dynamic>;
    } catch (_) {}
    final start = raw.indexOf('{');
    final end = raw.lastIndexOf('}');
    if (start >= 0 && end > start) {
      try {
        return jsonDecode(raw.substring(start, end + 1))
            as Map<String, dynamic>;
      } catch (_) {}
    }
    return null;
  }

  /// Parse one ReAct turn into either a [_ToolCall], [_FinalAnswer], or
  /// null if the model failed the required grammar.
  Object? _parseReactTurn(String raw) {
    final toolMatch =
        RegExp(r'<tool>\s*(\{[\s\S]*?\})\s*</tool>').firstMatch(raw);
    if (toolMatch != null) {
      final body = toolMatch.group(1)!;
      try {
        final obj = jsonDecode(body) as Map<String, dynamic>;
        final name = obj['name'] as String?;
        if (name == null || name.isEmpty) return null;
        final args = (obj['args'] as Map?)?.cast<String, dynamic>() ??
            <String, dynamic>{};
        return _ToolCall(name: name, args: args);
      } catch (_) {
        return null;
      }
    }
    final finalMatch =
        RegExp(r'<final>\s*(\{[\s\S]*?\})\s*</final>').firstMatch(raw);
    if (finalMatch != null) {
      final body = finalMatch.group(1)!;
      try {
        return _FinalAnswer(
            json: jsonDecode(body) as Map<String, dynamic>);
      } catch (_) {
        return null;
      }
    }
    return null;
  }
}

class _ToolCall {
  _ToolCall({required this.name, required this.args});
  final String name;
  final Map<String, dynamic> args;
}

class _FinalAnswer {
  _FinalAnswer({required this.json});
  final Map<String, dynamic> json;
}
