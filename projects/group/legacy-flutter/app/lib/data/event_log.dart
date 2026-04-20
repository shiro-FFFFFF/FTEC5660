import 'package:meta/meta.dart';
import 'package:riverpod/riverpod.dart';

import '../scenarios/events.dart';

@immutable
class EventLogEntry {
  const EventLogEntry({required this.event, this.riskScore, this.tags = const []});

  final ScamEvent event;
  final double? riskScore;
  final List<String> tags;

  EventLogEntry copyWith({double? riskScore, List<String>? tags}) {
    return EventLogEntry(
      event: event,
      riskScore: riskScore ?? this.riskScore,
      tags: tags ?? this.tags,
    );
  }
}

class EventLog extends Notifier<List<EventLogEntry>> {
  @override
  List<EventLogEntry> build() => const [];

  void add(ScamEvent event) {
    state = [...state, EventLogEntry(event: event)];
  }

  void annotate(String id, {double? risk, List<String>? tags}) {
    state = [
      for (final e in state)
        if (e.event.id == id)
          e.copyWith(riskScore: risk, tags: tags)
        else
          e,
    ];
  }

  void clear() {
    state = const [];
  }

  Iterable<ScamEvent> within(Duration window, {DateTime? now}) {
    final n = now ?? DateTime.now();
    final cutoff = n.subtract(window);
    return state
        .where((e) => e.event.timestamp.isAfter(cutoff))
        .map((e) => e.event);
  }
}

final eventLogProvider =
    NotifierProvider<EventLog, List<EventLogEntry>>(EventLog.new);
