import '../agents/context_agent.dart';
import '../agents/risk_agent.dart';
import '../scenarios/events.dart';
import 'llm_runtime.dart';
import 'tools.dart';

class HeuristicLlmRuntime implements LlmRuntime {
  @override
  bool get ready => true;

  @override
  String get name => 'heuristic';

  @override
  Future<void> warmup() async {}

  @override
  Future<LlmRiskOutput> scoreRisk({
    required ContextSnapshot snapshot,
    required double ruleScore,
    required List<RuleScoreContribution> ruleContributions,
    ToolRegistry? tools,
  }) async {
    final event = snapshot.triggeringEvent;
    final tactics = <String>{};
    final reasons = <String>[];

    String? text;
    switch (event) {
      case CallEvent():
        text = event.transcript;
      case SmsEvent():
        text = event.body;
      case ChatEvent():
        text = event.body;
      case TransactionEvent():
        text = null;
    }

    double lift = 0;
    if (text != null) {
      final lower = text.toLowerCase();
      if (lower.contains('police') ||
          lower.contains('arrest') ||
          lower.contains('cybercrime')) {
        tactics.add('authority_impersonation');
        reasons.add('Caller claims to be an authority.');
        lift += 0.2;
      }
      if (lower.contains('holding account') ||
          lower.contains('transfer your funds')) {
        tactics.add('payment_redirect');
        reasons.add('Asks you to move money to a "safe" account.');
        lift += 0.3;
      }
      if (lower.contains("don't tell") ||
          lower.contains('do not tell') ||
          lower.contains('confidential')) {
        tactics.add('isolation');
        reasons.add('Tells you to keep this secret.');
        lift += 0.2;
      }
      if (lower.contains('guaranteed') || lower.contains('vip tip')) {
        tactics.add('investment_scam');
        reasons.add('Offers "guaranteed" or insider returns.');
        lift += 0.2;
      }
      if (lower.contains('customs') || lower.contains('parcel')) {
        tactics.add('courier_scam');
        reasons.add('Uses a courier / customs pretext.');
        lift += 0.15;
      }
      if (lower.contains('urgent') ||
          lower.contains('immediately') ||
          lower.contains('final notice') ||
          lower.contains('hurry')) {
        tactics.add('urgency');
        reasons.add('Creates strong time pressure.');
        lift += 0.1;
      }
    }

    if (event is TransactionEvent) {
      if (snapshot.hasRecentCall && snapshot.secondsSinceLastCall < 600) {
        tactics.add('temporal_correlation');
        reasons.add('Transfer attempted right after a suspicious call.');
        lift += 0.2;
      }
      if (event.newRecipient && event.amountHkd >= 30000) {
        tactics.add('atypical_payee');
        reasons.add('Large transfer to a first-time payee.');
        lift += 0.15;
      }
    }

    final risk = (ruleScore * 0.6 + lift).clamp(0.0, 1.0);
    return LlmRiskOutput(
      risk: risk,
      tactics: tactics.toList(),
      reasons: reasons.isEmpty ? const ['Nothing obvious, erring low.'] : reasons,
      confidence: 0.4,
      source: 'heuristic',
    );
  }

  @override
  Future<String> explain({
    required ContextSnapshot snapshot,
    required double finalRisk,
  }) async {
    if (finalRisk >= 0.85) {
      return 'This looks like a classic scam pattern. Please pause and verify '
          'with someone you trust before continuing.';
    }
    if (finalRisk >= 0.6) {
      return 'Several signs here match common scam scripts. Take a moment '
          'before acting on this request.';
    }
    if (finalRisk >= 0.3) {
      return 'Something looks slightly off — worth a second look, but no '
          'immediate danger.';
    }
    return 'No suspicious signals detected.';
  }
}
