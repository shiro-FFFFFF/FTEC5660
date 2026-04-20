import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../agents/intervention_agent.dart';
import '../agents/risk_agent.dart';
import '../core/theme.dart';
import '../data/event_log.dart';
import '../llm/tools.dart';
import '../scenarios/events.dart';

class XaiScreen extends ConsumerWidget {
  const XaiScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final assessments = ref.watch(riskAgentProvider);
    final log = ref.watch(eventLogProvider);
    final interventions = ref.watch(interventionAgentProvider).history;
    final eventsById = {for (final e in log) e.event.id: e};

    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        title: const Text('Audit trail'),
      ),
      body: assessments.isEmpty
          ? const _Empty()
          : ListView.separated(
              padding: const EdgeInsets.all(16),
              itemCount: assessments.length,
              separatorBuilder: (_, _) => const SizedBox(height: 12),
              itemBuilder: (context, i) {
                final a = assessments[assessments.length - 1 - i];
                final entry = eventsById[a.eventId];
                InterventionAction? intervention;
                for (final x in interventions) {
                  if (x.eventId == a.eventId) {
                    intervention = x;
                    break;
                  }
                }
                return _AssessmentCard(
                  assessment: a,
                  entry: entry,
                  intervention: intervention,
                );
              },
            ),
    );
  }
}

class _AssessmentCard extends StatelessWidget {
  const _AssessmentCard({
    required this.assessment,
    required this.entry,
    required this.intervention,
  });
  final RiskAssessment assessment;
  final EventLogEntry? entry;
  final InterventionAction? intervention;

  @override
  Widget build(BuildContext context) {
    final color = RiskPalette.forRisk(assessment.finalRisk);
    final event = entry?.event;
    final subject = switch (event) {
      CallEvent(from: final f) => 'Call from $f',
      SmsEvent(from: final f) => 'SMS from $f',
      ChatEvent(contact: final c) => 'Chat with $c',
      TransactionEvent(toName: final t, amountHkd: final a) =>
        'Transfer HKD ${a.toStringAsFixed(0)} ??$t',
      _ => 'Event ${assessment.eventId}',
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(
                  child: Text(
                    subject,
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: color.withAlpha(30),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Text(
                    '${(assessment.finalRisk * 100).toStringAsFixed(0)}% · '
                    '${RiskPalette.labelFor(assessment.finalRisk)}',
                    style: TextStyle(color: color, fontWeight: FontWeight.w700),
                  ),
                ),
              ],
            ),
            if (event != null)
              Padding(
                padding: const EdgeInsets.only(top: 4),
                child: Text(
                  DateFormat('MMM d HH:mm:ss').format(event.timestamp),
                  style: const TextStyle(color: Colors.black54),
                ),
              ),
            const Divider(height: 24),
            _row('Fast rule score', assessment.fastRisk.toStringAsFixed(2)),
            _row('LLM score', assessment.llmRisk?.toStringAsFixed(2) ?? 'n/a'),
            _row(
              'LLM confidence',
              assessment.llmConfidence?.toStringAsFixed(2) ?? 'n/a',
            ),
            _row(
              'Reviewer score',
              assessment.reviewerRisk?.toStringAsFixed(2) ?? 'n/a',
            ),
            _row('Consensus', assessment.consensus),
            _row('Fused score', assessment.finalRisk.toStringAsFixed(2)),
            _row('Source', assessment.source),
            _row('Latency', '${assessment.latencyMs} ms'),
            const SizedBox(height: 12),
            if (assessment.contributions.isNotEmpty) ...[
              Text(
                'Rule contributions',
                style: Theme.of(context).textTheme.titleSmall,
              ),
              const SizedBox(height: 6),
              for (final c in assessment.contributions)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    children: [
                      SizedBox(
                        width: 80,
                        child: Text(
                          c.feature,
                          style: const TextStyle(
                            fontSize: 12,
                            fontFamily: 'monospace',
                          ),
                        ),
                      ),
                      Expanded(
                        child: LinearProgressIndicator(
                          value: c.value.clamp(0.0, 1.0),
                          minHeight: 6,
                          backgroundColor: Colors.grey.shade200,
                          valueColor: AlwaysStoppedAnimation<Color>(color),
                        ),
                      ),
                      const SizedBox(width: 8),
                      Text('+${c.value.toStringAsFixed(2)}'),
                    ],
                  ),
                ),
              const SizedBox(height: 8),
              for (final c in assessment.contributions)
                Text(
                  '??${c.detail}',
                  style: const TextStyle(color: Colors.black54, fontSize: 13),
                ),
            ],
            if (assessment.reasons.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text('Reasons', style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 6),
              for (final r in assessment.reasons) Text('??$r'),
            ],
            if (assessment.tactics.isNotEmpty) ...[
              const SizedBox(height: 12),
              Text('Tactics', style: Theme.of(context).textTheme.titleSmall),
              const SizedBox(height: 6),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final t in assessment.tactics)
                    Chip(
                      label: Text(
                        t.replaceAll('_', ' '),
                        style: const TextStyle(fontSize: 12),
                      ),
                      backgroundColor: Colors.grey.shade100,
                    ),
                ],
              ),
            ],
            if (assessment.toolTrace.isNotEmpty) ...[
              const SizedBox(height: 12),
              _AgentTraceSection(trace: assessment.toolTrace),
            ],
            if (intervention != null) ...[
              const SizedBox(height: 12),
              Container(
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: color.withAlpha(15),
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: color.withAlpha(60)),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Intervention: ${intervention!.level.name}',
                      style: TextStyle(
                        color: color,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    if (intervention!.overridden)
                      const Text('User overrode the warning.'),
                    if (intervention!.dismissed)
                      const Text('User dismissed the banner.'),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _row(String k, String v) => Padding(
    padding: const EdgeInsets.symmetric(vertical: 2),
    child: Row(
      children: [
        SizedBox(
          width: 140,
          child: Text(k, style: const TextStyle(color: Colors.black54)),
        ),
        Text(v, style: const TextStyle(fontWeight: FontWeight.w600)),
      ],
    ),
  );
}

class _AgentTraceSection extends StatelessWidget {
  const _AgentTraceSection({required this.trace});
  final List<ToolCallStep> trace;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            const Icon(
              Icons.psychology_outlined,
              size: 18,
              color: Color(0xFF005A9C),
            ),
            const SizedBox(width: 6),
            Text(
              'Agent reasoning (${trace.length} tool call${trace.length == 1 ? "" : "s"})',
              style: Theme.of(context).textTheme.titleSmall,
            ),
          ],
        ),
        const SizedBox(height: 6),
        for (var i = 0; i < trace.length; i++)
          _TraceStep(step: trace[i], index: i + 1),
      ],
    );
  }
}

class _TraceStep extends StatelessWidget {
  const _TraceStep({required this.step, required this.index});
  final ToolCallStep step;
  final int index;

  @override
  Widget build(BuildContext context) {
    final args = step.args.isEmpty ? '' : jsonEncode(step.args);
    final result = _summariseResult(step.result);
    return Container(
      margin: const EdgeInsets.only(top: 6),
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
      decoration: BoxDecoration(
        color: const Color(0xFFF5F8FC),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: const Color(0xFFD9E3EE)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 22,
                height: 22,
                alignment: Alignment.center,
                decoration: const BoxDecoration(
                  color: Color(0xFF005A9C),
                  shape: BoxShape.circle,
                ),
                child: Text(
                  '$index',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 12,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  '${step.tool}($args)',
                  style: const TextStyle(
                    fontFamily: 'monospace',
                    fontSize: 12.5,
                    fontWeight: FontWeight.w600,
                  ),
                ),
              ),
              Text(
                '${step.latencyMs} ms',
                style: const TextStyle(color: Colors.black54, fontSize: 11),
              ),
            ],
          ),
          const SizedBox(height: 4),
          Padding(
            padding: const EdgeInsets.only(left: 30),
            child: Text(
              '??$result',
              style: const TextStyle(
                fontFamily: 'monospace',
                fontSize: 12,
                color: Colors.black87,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String _summariseResult(Map<String, dynamic> result) {
    // Short, human-readable summary; full JSON is available from toJson().
    if (result['hit'] == true) {
      final tag = result['tag'] ?? result['matches']?[0]?['tag'] ?? '?';
      final weight = result['weight'] ?? result['matches']?[0]?['weight'];
      return weight != null ? 'hit (tag=$tag, w=$weight)' : 'hit (tag=$tag)';
    }
    if (result['hit'] == false) return 'no hit';
    if (result['count'] != null) {
      return '${result['count']} keyword hit(s), total_weight=${result['total_weight']}';
    }
    if (result['recent_event_count'] != null) {
      final ch = result['channels'] as Map? ?? const {};
      return '${result['recent_event_count']} events | call=${ch['call']} sms=${ch['sms']} '
          'chat=${ch['chat']} txn=${ch['transaction']}';
    }
    final preview = jsonEncode(result);
    return preview.length <= 160 ? preview : '${preview.substring(0, 157)}...';
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.shield_outlined, size: 64, color: Colors.grey.shade400),
            const SizedBox(height: 16),
            Text(
              'No assessments yet. Play a scenario from the home screen.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey.shade700, fontSize: 16),
            ),
          ],
        ),
      ),
    );
  }
}
