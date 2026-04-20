import 'dart:developer' as dev;

import 'package:meta/meta.dart';
import 'package:riverpod/riverpod.dart';

import '../data/event_log.dart';
import '../data/scam_db.dart';
import '../llm/heuristic_runtime.dart';
import '../llm/llm_runtime.dart';
import '../llm/tools.dart';
import '../scenarios/events.dart';
import 'context_agent.dart';
import 'intervention_agent.dart';

@immutable
class RuleScoreContribution {
  const RuleScoreContribution({
    required this.feature,
    required this.value,
    required this.detail,
  });

  final String feature;
  final double value;
  final String detail;
}

@immutable
class RiskAssessment {
  const RiskAssessment({
    required this.eventId,
    required this.fastRisk,
    required this.llmRisk,
    required this.finalRisk,
    required this.contributions,
    required this.tactics,
    required this.reasons,
    required this.latencyMs,
    required this.source,
    this.llmConfidence,
    this.reviewerRisk,
    this.consensus = 'rule_only',
    this.toolTrace = const [],
  });

  final String eventId;
  final double fastRisk;
  final double? llmRisk;
  final double finalRisk;
  final List<RuleScoreContribution> contributions;
  final List<String> tactics;
  final List<String> reasons;
  final int latencyMs;
  final String source;
  final double? llmConfidence;
  final double? reviewerRisk;
  final String consensus;

  /// Ordered record of agent orchestration + ReAct tool calls.
  final List<ToolCallStep> toolTrace;

  Map<String, dynamic> toJson() => {
    'event_id': eventId,
    'fast_risk': fastRisk,
    'llm_risk': llmRisk,
    'llm_confidence': llmConfidence,
    'reviewer_risk': reviewerRisk,
    'final_risk': finalRisk,
    'contributions': [
      for (final c in contributions)
        {'feature': c.feature, 'value': c.value, 'detail': c.detail},
    ],
    'tactics': tactics,
    'reasons': reasons,
    'latency_ms': latencyMs,
    'source': source,
    'consensus': consensus,
    'tool_trace': [for (final t in toolTrace) t.toJson()],
  };
}

class RiskAgent extends Notifier<List<RiskAssessment>> {
  @override
  List<RiskAssessment> build() => const [];

  Future<RiskAssessment> assess(ContextSnapshot snapshot) async {
    final started = DateTime.now();
    final db = ref.read(scamDatabaseProvider);
    final fast = _ruleScore(snapshot, db);
    final event = snapshot.triggeringEvent;
    final llmRequested = _shouldCallLlm(event, fast.score);

    final orchestrationTrace = <ToolCallStep>[
      _metaTrace(
        tool: 'orchestrator_plan',
        args: {'event_kind': event.kind.name, 'fast_risk': _round(fast.score)},
        result: {
          'llm_requested': llmRequested,
          'priority': _priorityFor(event, fast.score),
        },
      ),
    ];

    double finalRisk = fast.score;
    double? llmRisk;
    double? llmConfidence;
    double? reviewerRisk;
    List<String> llmTactics = const [];
    List<String> llmReasons = const [];
    List<ToolCallStep> llmTrace = const [];
    String consensus = 'rule_only';
    String source = 'rule';

    if (llmRequested) {
      try {
        final llm = ref.read(llmRuntimeProvider);
        final tools = buildDefaultToolRegistry(db: db, snapshot: snapshot);
        final out = await llm.scoreRisk(
          snapshot: snapshot,
          ruleScore: fast.score,
          ruleContributions: fast.contributions,
          tools: tools,
        );

        llmRisk = out.risk;
        llmConfidence = out.confidence;
        llmTactics = out.tactics;
        llmReasons = out.reasons;
        llmTrace = out.trace;
        finalRisk = _fuse(fast.score, out.risk);
        consensus = 'single_agent';
        source = out.source;

        if (_shouldRunSecondOpinion(
          event: event,
          fastRisk: fast.score,
          llmRisk: out.risk,
          llmConfidence: out.confidence,
        )) {
          final reviewStarted = DateTime.now();
          final reviewer = HeuristicLlmRuntime();
          final review = await reviewer.scoreRisk(
            snapshot: snapshot,
            ruleScore: fast.score,
            ruleContributions: fast.contributions,
            tools: null,
          );
          final reviewMs = DateTime.now()
              .difference(reviewStarted)
              .inMilliseconds;

          reviewerRisk = review.risk;
          consensus = _consensusLabel(out.risk, review.risk);
          finalRisk = _fuseWithReview(
            fast: fast.score,
            llm: out.risk,
            reviewer: review.risk,
            consensus: consensus,
          );

          if (consensus == 'conflict') {
            llmReasons = [
              ...llmReasons,
              'AI agents disagree. Verify with a trusted contact before acting.',
            ];
          }

          orchestrationTrace.add(
            _metaTrace(
              tool: 'orchestrator_second_opinion',
              args: {
                'llm_risk': _round(out.risk),
                'llm_confidence': _round(out.confidence),
              },
              result: {
                'reviewer': reviewer.name,
                'reviewer_risk': _round(review.risk),
                'consensus': consensus,
              },
              latencyMs: reviewMs,
            ),
          );
          source = '$source+review';
        }
      } catch (e) {
        dev.log('[risk] LLM scoring failed: $e', name: 'risk');
      }
    }

    orchestrationTrace.add(
      _metaTrace(
        tool: 'orchestrator_decision',
        args: {
          'fast_risk': _round(fast.score),
          'llm_risk': llmRisk != null ? _round(llmRisk) : null,
          'reviewer_risk': reviewerRisk != null ? _round(reviewerRisk) : null,
        },
        result: {
          'final_risk': _round(finalRisk),
          'consensus': consensus,
          'source': source,
        },
      ),
    );

    final elapsed = DateTime.now().difference(started).inMilliseconds;
    final assessment = RiskAssessment(
      eventId: event.id,
      fastRisk: fast.score,
      llmRisk: llmRisk,
      llmConfidence: llmConfidence,
      reviewerRisk: reviewerRisk,
      finalRisk: finalRisk.clamp(0.0, 1.0),
      contributions: fast.contributions,
      tactics: llmTactics.isNotEmpty
          ? llmTactics
          : fast.contributions.map((c) => c.feature).toList(),
      reasons: llmReasons.isNotEmpty ? llmReasons : fast.reasons,
      latencyMs: elapsed,
      source: source,
      consensus: consensus,
      toolTrace: [...orchestrationTrace, ...llmTrace],
    );

    state = [...state, assessment];
    ref
        .read(eventLogProvider.notifier)
        .annotate(
          event.id,
          risk: assessment.finalRisk,
          tags: assessment.tactics,
        );

    dev.log(
      '[risk] ${event.kind.name}/${event.id} '
      'fast=${fast.score.toStringAsFixed(2)} '
      'llm=${llmRisk?.toStringAsFixed(2) ?? '-'} '
      'review=${reviewerRisk?.toStringAsFixed(2) ?? '-'} '
      'final=${assessment.finalRisk.toStringAsFixed(2)} '
      '[${assessment.consensus}] '
      '(${elapsed}ms, $source)',
      name: 'risk',
    );

    await ref
        .read(interventionAgentProvider.notifier)
        .decide(assessment, snapshot);
    return assessment;
  }

  bool _shouldCallLlm(ScamEvent event, double fastRisk) {
    if (event is TransactionEvent) return true;
    if (event is CallEvent || event is ChatEvent) return fastRisk >= 0.25;
    if (event is SmsEvent) return fastRisk >= 0.3;
    return false;
  }

  bool _shouldRunSecondOpinion({
    required ScamEvent event,
    required double fastRisk,
    required double llmRisk,
    required double llmConfidence,
  }) {
    if (event is TransactionEvent) return true;
    if ((llmRisk - fastRisk).abs() >= 0.35) return true;
    if (llmConfidence < 0.55) return true;
    return llmRisk >= 0.35 && llmRisk <= 0.8;
  }

  String _consensusLabel(double llmRisk, double reviewerRisk) {
    final gap = (llmRisk - reviewerRisk).abs();
    if (gap <= 0.15) return 'aligned';
    if (gap <= 0.35) return 'mixed';
    return 'conflict';
  }

  double _fuse(double fast, double llm) =>
      [fast, 0.6 * llm + 0.4 * fast].reduce((a, b) => a > b ? a : b);

  double _fuseWithReview({
    required double fast,
    required double llm,
    required double reviewer,
    required String consensus,
  }) {
    final base = _fuse(fast, llm);
    final blended = 0.5 * llm + 0.3 * reviewer + 0.2 * fast;
    if (consensus == 'conflict') {
      final conservative = 0.25 * llm + 0.55 * reviewer + 0.2 * fast;
      return [fast, reviewer, conservative].reduce((a, b) => a > b ? a : b);
    }
    return [base, blended].reduce((a, b) => a > b ? a : b);
  }

  String _priorityFor(ScamEvent event, double fastRisk) {
    if (event is TransactionEvent) return 'critical';
    if (fastRisk >= 0.75) return 'high';
    if (fastRisk >= 0.3) return 'medium';
    return 'low';
  }

  ToolCallStep _metaTrace({
    required String tool,
    required Map<String, dynamic> args,
    required Map<String, dynamic> result,
    int latencyMs = 0,
  }) {
    return ToolCallStep(
      tool: tool,
      args: args,
      result: result,
      latencyMs: latencyMs,
    );
  }

  double _round(double value) => double.parse(value.toStringAsFixed(3));

  _RuleResult _ruleScore(ContextSnapshot s, ScamDatabase? db) {
    final contribs = <RuleScoreContribution>[];
    final reasons = <String>[];
    final event = s.triggeringEvent;
    double score = 0;

    String? from;
    String? text;
    switch (event) {
      case CallEvent():
        from = event.from;
        text = event.transcript;
      case SmsEvent():
        from = event.from;
        text = event.body;
      case ChatEvent():
        from = event.contact;
        text = event.body;
      case TransactionEvent():
        from = null;
        text = null;
    }

    if (db != null) {
      if (from != null) {
        for (final bad in db.badNumbers()) {
          if (from.toLowerCase().contains(bad.value)) {
            score += bad.weight;
            contribs.add(
              RuleScoreContribution(
                feature: 'bad_number',
                value: bad.weight,
                detail: 'Sender $from on blocklist (${bad.tag})',
              ),
            );
            reasons.add('Sender number is on a scam blocklist.');
          }
        }
      }
      if (text != null) {
        final lower = text.toLowerCase();
        for (final d in db.badDomains()) {
          if (lower.contains(d.value)) {
            score += d.weight;
            contribs.add(
              RuleScoreContribution(
                feature: 'bad_domain',
                value: d.weight,
                detail: 'Message contains phishing domain ${d.value}',
              ),
            );
            reasons.add('Message contains a known phishing link.');
          }
        }
        double kwSum = 0;
        final hits = <String>[];
        for (final k in db.keywords()) {
          if (lower.contains(k.value)) {
            kwSum += k.weight;
            hits.add('"${k.value}" (${k.tag})');
          }
        }
        if (hits.isNotEmpty) {
          final bounded = (kwSum * 0.5).clamp(0.0, 0.9);
          score += bounded;
          contribs.add(
            RuleScoreContribution(
              feature: 'scam_keywords',
              value: bounded,
              detail:
                  'Matched ${hits.length} keyword(s): ${hits.take(4).join(', ')}'
                  '${hits.length > 4 ? ', ...' : ''}',
            ),
          );
          reasons.add('Language matches common scam scripts.');
        }
      }
    }

    if (s.priorMaxRisk >= 0.5 && event is! TransactionEvent) {
      final bump = ((s.priorMaxRisk - 0.3) * 0.5).clamp(0.0, 0.25);
      score += bump;
      contribs.add(
        RuleScoreContribution(
          feature: 'scam_thread',
          value: bump,
          detail:
              'Earlier events in this window scored ${(s.priorMaxRisk * 100).toStringAsFixed(0)}%',
        ),
      );
      reasons.add('This is part of an ongoing suspicious conversation.');
    }

    if (event is TransactionEvent) {
      double txn = 0;
      if (event.newRecipient) {
        txn += 0.35;
        contribs.add(
          const RuleScoreContribution(
            feature: 'new_recipient',
            value: 0.35,
            detail: 'First-time payee',
          ),
        );
      }
      if (event.amountHkd >= 30000) {
        txn += 0.25;
        contribs.add(
          RuleScoreContribution(
            feature: 'large_amount',
            value: 0.25,
            detail:
                '${event.amountHkd.toStringAsFixed(0)} HKD above daily pattern',
          ),
        );
      } else if (event.amountHkd >= 10000) {
        txn += 0.1;
        contribs.add(
          RuleScoreContribution(
            feature: 'elevated_amount',
            value: 0.1,
            detail: '${event.amountHkd.toStringAsFixed(0)} HKD above typical',
          ),
        );
      }
      if (s.hasRecentCall && s.secondsSinceLastCall < 300) {
        txn += 0.25;
        contribs.add(
          RuleScoreContribution(
            feature: 'temporal_call',
            value: 0.25,
            detail: 'Call ${s.secondsSinceLastCall}s ago',
          ),
        );
        reasons.add('Large transfer initiated right after a phone call.');
      }
      if (s.hasRecentSms && s.secondsSinceLastSms < 600) {
        txn += 0.15;
        contribs.add(
          RuleScoreContribution(
            feature: 'temporal_sms',
            value: 0.15,
            detail: 'SMS ${s.secondsSinceLastSms}s ago',
          ),
        );
      }
      score += txn;
      if (event.newRecipient && event.amountHkd >= 10000) {
        reasons.add('Large transfer to a new recipient.');
      }
    }

    final clamped = score.clamp(0.0, 1.0);
    if (reasons.isEmpty) {
      reasons.add('No rule triggered.');
    }
    return _RuleResult(
      score: clamped,
      contributions: contribs,
      reasons: reasons,
    );
  }
}

class _RuleResult {
  const _RuleResult({
    required this.score,
    required this.contributions,
    required this.reasons,
  });

  final double score;
  final List<RuleScoreContribution> contributions;
  final List<String> reasons;
}

final riskAgentProvider = NotifierProvider<RiskAgent, List<RiskAssessment>>(
  RiskAgent.new,
);
