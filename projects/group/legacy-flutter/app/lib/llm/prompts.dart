import 'dart:convert';

import '../agents/context_agent.dart';
import '../agents/risk_agent.dart';
import '../scenarios/events.dart';
import 'tools.dart';

const String riskSystemPrompt = '''
You are Guardian, an anti-scam decision support agent for elderly banking users.
You will receive a TRIGGER event and a short CONTEXT history.
Output a STRICT JSON object matching this schema, with no prose:

{"risk": <number 0-1>, "tactics": [<string>...], "reasons": [<short sentence>...], "confidence": <number 0-1>}

Guidelines:
- risk closer to 1 means higher probability the user is being scammed.
- tactics come from this allowed set (pick any that apply):
  authority_impersonation, urgency, isolation, payment_redirect,
  investment_scam, romance_scam, courier_scam, credential_theft,
  temporal_correlation, atypical_payee, unverified_link
- reasons must be plain-language, max 12 words each, elderly-friendly.
- Never invent facts not present in the input.
''';

String buildRiskPrompt({
  required ContextSnapshot snapshot,
  required double ruleScore,
  required List<RuleScoreContribution> ruleContributions,
}) {
  final trig = _describeEvent(snapshot.triggeringEvent);
  final ctx = snapshot.recentEvents
      .where((e) => e.id != snapshot.triggeringEvent.id)
      .map(_describeEvent)
      .toList();
  final ruleSummary = ruleContributions
      .map((c) => '- ${c.feature} (+${c.value.toStringAsFixed(2)}): ${c.detail}')
      .join('\n');
  final buf = StringBuffer()
    ..writeln('TRIGGER:')
    ..writeln(trig)
    ..writeln()
    ..writeln('CONTEXT (most recent first, up to 5):');
  for (final line in ctx.reversed.take(5)) {
    buf.writeln('- $line');
  }
  buf
    ..writeln()
    ..writeln('RULE SCORE: ${ruleScore.toStringAsFixed(2)}')
    ..writeln('RULE CONTRIBUTIONS:')
    ..writeln(ruleSummary.isEmpty ? '(none)' : ruleSummary)
    ..writeln()
    ..writeln('Respond with ONLY the JSON object.');
  return buf.toString();
}

String _describeEvent(ScamEvent e) {
  switch (e) {
    case CallEvent():
      return 'Call from "${e.from}" — transcript: "${_trim(e.transcript)}"';
    case SmsEvent():
      return 'SMS from "${e.from}" — body: "${_trim(e.body)}"';
    case ChatEvent():
      return 'Chat from "${e.contact}" — body: "${_trim(e.body)}"';
    case TransactionEvent():
      return 'Transfer attempt: HKD ${e.amountHkd.toStringAsFixed(0)} → '
          '"${e.toName}" (${e.toAccount})'
          '${e.newRecipient ? ", NEW recipient" : ""}';
  }
}

String _trim(String s, [int max = 220]) {
  final clean = s.replaceAll('\n', ' ').trim();
  return clean.length <= max ? clean : '${clean.substring(0, max)}…';
}

/// System prompt that instructs the model to behave as a tool-using
/// ReAct agent. It lists available tools, specifies a strict
/// response grammar, and asks for a final JSON answer.
String buildReactSystemPrompt(ToolRegistry tools) {
  final enc = const JsonEncoder.withIndent('  ');
  final schemas = enc.convert(tools.schemas());
  return '''
You are Guardian, an anti-scam decision agent for elderly banking users.
You evaluate a TRIGGER event plus CONTEXT and decide a risk score.

You can CALL TOOLS to gather evidence before deciding. The available tools are:

$schemas

RESPONSE GRAMMAR — every reply MUST be exactly one of:

  <tool>{"name": "<tool_name>", "args": {...}}</tool>
  <final>{"risk": <0-1>, "tactics": [...], "reasons": [...], "confidence": <0-1>}</final>

Rules:
- Emit exactly ONE tag per reply. No prose outside the tag.
- After each <tool> call, the next user message will contain an <observation>
  tag with JSON results. Use it to decide your next action.
- Prefer to run 1–3 tools when the trigger is ambiguous; skip tools when the
  signal is already obvious.
- Maximum 4 tool calls per decision — after that you MUST emit <final>.
- The "tactics" field in <final> must come from this set:
  authority_impersonation, urgency, isolation, payment_redirect,
  investment_scam, romance_scam, courier_scam, credential_theft,
  temporal_correlation, atypical_payee, unverified_link.
- "reasons" are short plain-language sentences (≤ 12 words, elderly-friendly).
- Never invent facts not present in input or tool observations.
''';
}
