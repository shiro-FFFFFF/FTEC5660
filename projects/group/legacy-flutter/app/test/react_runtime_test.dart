import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:guardian/agents/context_agent.dart';
import 'package:guardian/data/scam_db.dart';
import 'package:guardian/llm/ollama_runtime.dart';
import 'package:guardian/llm/tools.dart';
import 'package:guardian/scenarios/events.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart' as httptest;

/// Minimal scam database with one bad number and one bad domain so the
/// ReAct tools have something to hit.
ScamDatabase _db() => ScamDatabase.fromCsv(
      'type,value,weight,tag,note\n'
      'number,+852 0000 0001,0.9,spoof_police,test\n'
      'domain,verify-id.top,0.9,phishing,test\n'
      'keyword,urgent,0.4,urgency,test\n',
    );

/// Fake SmsEvent-based snapshot (no prior history).
ContextSnapshot _snap() => ContextSnapshot(
      triggeringEvent: SmsEvent(
        id: 't1',
        timestamp: DateTime(2026, 4, 18, 20, 0),
        from: '+852 0000 0001',
        body: 'URGENT: verify at http://verify-id.top/login',
      ),
      recentEvents: const [],
      now: DateTime(2026, 4, 18, 20, 0),
      hasRecentCall: false,
      hasRecentSms: false,
      hasRecentChat: false,
      secondsSinceLastCall: 1 << 30,
      secondsSinceLastSms: 1 << 30,
      priorMaxRisk: 0,
    );

/// A scripted chat server that emits a canned sequence of assistant replies,
/// one per POST to /api/chat.
http.Client _scriptedClient(List<String> replies) {
  var i = 0;
  return httptest.MockClient((req) async {
    if (!req.url.path.endsWith('/api/chat')) {
      return http.Response('', 404);
    }
    final reply = i < replies.length ? replies[i++] : replies.last;
    final body = jsonEncode({
      'model': 'test',
      'message': {'role': 'assistant', 'content': reply},
    });
    return http.Response(body, 200,
        headers: const {'content-type': 'application/json'});
  });
}

void main() {
  test('ReAct loop: model calls tools then commits final answer', () async {
    final runtime = OllamaLlmRuntime(
      model: 'test',
      client: _scriptedClient([
        // Step 1: inspect the sender.
        '<tool>{"name": "lookup_number", "args": {"number": "+852 0000 0001"}}</tool>',
        // Step 2: inspect the URL in the body.
        '<tool>{"name": "check_domain", "args": {"text": "http://verify-id.top/login"}}</tool>',
        // Step 3: commit verdict.
        '<final>{"risk": 0.95, "tactics": ["credential_theft","urgency"], '
            '"reasons": ["Sender on scam blocklist.","Link is a phishing domain."], '
            '"confidence": 0.85}</final>',
      ]),
    );
    final tools = buildDefaultToolRegistry(db: _db(), snapshot: _snap());

    final out = await runtime.scoreRisk(
      snapshot: _snap(),
      ruleScore: 0.4,
      ruleContributions: const [],
      tools: tools,
    );

    expect(out.risk, closeTo(0.95, 1e-6));
    expect(out.tactics, containsAll(['credential_theft', 'urgency']));
    expect(out.trace, hasLength(2));
    expect(out.trace[0].tool, 'lookup_number');
    expect(out.trace[0].result['hit'], true);
    expect(out.trace[0].result['tag'], 'spoof_police');
    expect(out.trace[1].tool, 'check_domain');
    expect(out.trace[1].result['hit'], true);
    expect(out.source, contains('react'));
  });

  test('ReAct loop: recovers from unknown tool name', () async {
    final runtime = OllamaLlmRuntime(
      model: 'test',
      client: _scriptedClient([
        '<tool>{"name": "does_not_exist", "args": {}}</tool>',
        '<final>{"risk": 0.2, "tactics": [], "reasons": ["Not enough signal."], '
            '"confidence": 0.4}</final>',
      ]),
    );
    final tools = buildDefaultToolRegistry(db: _db(), snapshot: _snap());

    final out = await runtime.scoreRisk(
      snapshot: _snap(),
      ruleScore: 0.1,
      ruleContributions: const [],
      tools: tools,
    );

    expect(out.risk, closeTo(0.2, 1e-6));
    // Unknown tool did not produce a trace entry; the model still reached
    // a final verdict on the next turn.
    expect(out.trace, isEmpty);
  });

  test('ReAct loop: single-shot fallback when tools is null', () async {
    final runtime = OllamaLlmRuntime(
      model: 'test',
      client: _scriptedClient([
        '{"risk": 0.77, "tactics": ["urgency"], "reasons": ["Pressure tactic."], '
            '"confidence": 0.6}',
      ]),
    );

    final out = await runtime.scoreRisk(
      snapshot: _snap(),
      ruleScore: 0.3,
      ruleContributions: const [],
      tools: null, // no tools → single-shot path
    );

    expect(out.risk, closeTo(0.77, 1e-6));
    expect(out.trace, isEmpty);
    expect(out.source, isNot(contains('react')));
  });
}
