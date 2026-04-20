import 'dart:developer' as dev;

import 'package:meta/meta.dart';
import 'package:riverpod/riverpod.dart';

import '../data/event_log.dart';
import '../scenarios/events.dart';
import 'risk_agent.dart';

@immutable
class ContextSnapshot {
  const ContextSnapshot({
    required this.triggeringEvent,
    required this.recentEvents,
    required this.now,
    required this.hasRecentCall,
    required this.hasRecentSms,
    required this.hasRecentChat,
    required this.secondsSinceLastCall,
    required this.secondsSinceLastSms,
    required this.priorMaxRisk,
  });

  final ScamEvent triggeringEvent;
  final List<ScamEvent> recentEvents;
  final DateTime now;
  final bool hasRecentCall;
  final bool hasRecentSms;
  final bool hasRecentChat;
  final int secondsSinceLastCall;
  final int secondsSinceLastSms;
  final double priorMaxRisk;

  int get recentEventCount => recentEvents.length;
}

class ContextAgent extends Notifier<ContextSnapshot?> {
  static const Duration _window = Duration(hours: 72);

  @override
  ContextSnapshot? build() => null;

  Future<void> ingest(ScamEvent event) async {
    final logNotifier = ref.read(eventLogProvider.notifier);
    logNotifier.add(event);
    final entries = ref.read(eventLogProvider);
    final recent = logNotifier.within(_window, now: event.timestamp).toList();
    final priorMaxRisk = entries
        .where((e) => e.event.id != event.id && e.riskScore != null)
        .map((e) => e.riskScore!)
        .fold<double>(0, (a, b) => a > b ? a : b);
    final snapshot = _buildSnapshot(event, recent, priorMaxRisk);
    state = snapshot;
    dev.log(
      '[context] ingested ${event.kind.name} — ${recent.length} event(s), '
      'prior max risk ${priorMaxRisk.toStringAsFixed(2)}',
      name: 'context',
    );
    await ref.read(riskAgentProvider.notifier).assess(snapshot);
  }

  ContextSnapshot _buildSnapshot(
    ScamEvent trigger,
    List<ScamEvent> recent,
    double priorMaxRisk,
  ) {
    CallEvent? lastCall;
    SmsEvent? lastSms;
    bool hasChat = false;
    for (final e in recent) {
      switch (e) {
        case CallEvent():
          if (lastCall == null || e.timestamp.isAfter(lastCall.timestamp)) {
            lastCall = e;
          }
        case SmsEvent():
          if (lastSms == null || e.timestamp.isAfter(lastSms.timestamp)) {
            lastSms = e;
          }
        case ChatEvent():
          hasChat = true;
        case TransactionEvent():
          break;
      }
    }
    final now = trigger.timestamp;
    return ContextSnapshot(
      triggeringEvent: trigger,
      recentEvents: recent,
      now: now,
      hasRecentCall: lastCall != null,
      hasRecentSms: lastSms != null,
      hasRecentChat: hasChat,
      secondsSinceLastCall: lastCall == null
          ? 1 << 30
          : now.difference(lastCall.timestamp).inSeconds,
      secondsSinceLastSms: lastSms == null
          ? 1 << 30
          : now.difference(lastSms.timestamp).inSeconds,
      priorMaxRisk: priorMaxRisk,
    );
  }
}

final contextAgentProvider =
    NotifierProvider<ContextAgent, ContextSnapshot?>(ContextAgent.new);
