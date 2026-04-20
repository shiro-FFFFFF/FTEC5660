import 'dart:developer' as dev;

import 'package:meta/meta.dart';
import 'package:riverpod/riverpod.dart';

import '../scenarios/events.dart';
import 'context_agent.dart';
import 'risk_agent.dart';

enum InterventionLevel { none, banner, fullScreen, delay }

@immutable
class InterventionAction {
  const InterventionAction({
    required this.id,
    required this.level,
    required this.risk,
    required this.headline,
    required this.body,
    required this.eventId,
    required this.createdAt,
    this.cooldownSeconds = 0,
    this.dismissed = false,
    this.overridden = false,
  });

  final String id;
  final InterventionLevel level;
  final double risk;
  final String headline;
  final String body;
  final String eventId;
  final DateTime createdAt;
  final int cooldownSeconds;
  final bool dismissed;
  final bool overridden;

  InterventionAction copyWith({bool? dismissed, bool? overridden}) {
    return InterventionAction(
      id: id,
      level: level,
      risk: risk,
      headline: headline,
      body: body,
      eventId: eventId,
      createdAt: createdAt,
      cooldownSeconds: cooldownSeconds,
      dismissed: dismissed ?? this.dismissed,
      overridden: overridden ?? this.overridden,
    );
  }
}

@immutable
class InterventionState {
  const InterventionState({
    this.pending,
    this.ambient,
    this.history = const [],
  });

  final InterventionAction? pending;
  final InterventionAction? ambient;
  final List<InterventionAction> history;

  InterventionState copyWith({
    InterventionAction? pending,
    bool clearPending = false,
    InterventionAction? ambient,
    bool clearAmbient = false,
    List<InterventionAction>? history,
  }) {
    return InterventionState(
      pending: clearPending ? null : (pending ?? this.pending),
      ambient: clearAmbient ? null : (ambient ?? this.ambient),
      history: history ?? this.history,
    );
  }
}

class InterventionAgent extends Notifier<InterventionState> {
  int _counter = 0;

  @override
  InterventionState build() => const InterventionState();

  Future<void> decide(
    RiskAssessment assessment,
    ContextSnapshot context,
  ) async {
    final level = _levelFor(assessment.finalRisk, context.triggeringEvent);
    if (level == InterventionLevel.none) {
      dev.log(
        '[intervention] risk=${assessment.finalRisk.toStringAsFixed(2)} → silent',
        name: 'intervention',
      );
      return;
    }
    final action = InterventionAction(
      id: 'i${++_counter}',
      level: level,
      risk: assessment.finalRisk,
      headline: _headlineFor(level, context.triggeringEvent),
      body: _bodyFor(assessment, context),
      eventId: context.triggeringEvent.id,
      createdAt: DateTime.now(),
      cooldownSeconds: switch (level) {
        InterventionLevel.fullScreen => 60,
        InterventionLevel.delay => 60 * 60 * 24,
        _ => 0,
      },
    );
    dev.log(
      '[intervention] risk=${assessment.finalRisk.toStringAsFixed(2)} → ${level.name}',
      name: 'intervention',
    );
    if (level == InterventionLevel.banner) {
      state = state.copyWith(
        ambient: action,
        history: [...state.history, action],
      );
    } else {
      state = state.copyWith(
        pending: action,
        history: [...state.history, action],
      );
    }
  }

  InterventionLevel _levelFor(double risk, ScamEvent event) {
    final isTxn = event is TransactionEvent;
    if (isTxn && risk >= 0.85) return InterventionLevel.delay;
    if (isTxn && risk >= 0.6) return InterventionLevel.fullScreen;
    if (risk >= 0.75) return InterventionLevel.fullScreen;
    if (risk >= 0.3) return InterventionLevel.banner;
    return InterventionLevel.none;
  }

  String _headlineFor(InterventionLevel level, ScamEvent event) {
    final subject = switch (event) {
      CallEvent() => 'this call',
      SmsEvent() => 'this message',
      ChatEvent() => 'this chat',
      TransactionEvent() => 'this transfer',
    };
    return switch (level) {
      InterventionLevel.banner => 'Something looks off about $subject',
      InterventionLevel.fullScreen => 'Pause — $subject looks like a scam',
      InterventionLevel.delay => '24-hour hold suggested on $subject',
      InterventionLevel.none => '',
    };
  }

  String _bodyFor(RiskAssessment a, ContextSnapshot c) {
    final bullets = <String>[];
    for (final reason in a.reasons.take(3)) {
      bullets.add('• $reason');
    }
    if (c.hasRecentCall && c.secondsSinceLastCall < 600) {
      bullets.add(
        '• You got a phone call ${(c.secondsSinceLastCall / 60).ceil()} minute(s) ago — scammers often follow up with pressure.',
      );
    }
    if (c.hasRecentSms && c.secondsSinceLastSms < 600) {
      bullets.add('• A suspicious message arrived recently.');
    }
    return bullets.join('\n');
  }

  void dismissAmbient() {
    final cur = state.ambient;
    if (cur == null) return;
    state = state.copyWith(
      clearAmbient: true,
      history: [
        for (final h in state.history)
          if (h.id == cur.id) h.copyWith(dismissed: true) else h,
      ],
    );
  }

  void overridePending() {
    final cur = state.pending;
    if (cur == null) return;
    state = state.copyWith(
      clearPending: true,
      history: [
        for (final h in state.history)
          if (h.id == cur.id) h.copyWith(overridden: true) else h,
      ],
    );
  }

  void resolvePending() {
    state = state.copyWith(clearPending: true);
  }

  void reset() {
    state = const InterventionState();
  }
}

final interventionAgentProvider =
    NotifierProvider<InterventionAgent, InterventionState>(
        InterventionAgent.new);
