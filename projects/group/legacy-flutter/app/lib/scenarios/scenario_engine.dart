import 'dart:async';
import 'dart:convert';
import 'dart:developer' as dev;

import 'package:flutter/services.dart';
import 'package:meta/meta.dart';
import 'package:riverpod/riverpod.dart';

import '../agents/context_agent.dart';
import 'events.dart';

@immutable
class Scenario {
  const Scenario({
    required this.id,
    required this.label,
    required this.category,
    required this.events,
    required this.expected,
  });

  final String id;
  final String label;
  final String category;
  final List<ScheduledEvent> events;
  final Map<String, dynamic> expected;

  factory Scenario.fromJson(Map<String, dynamic> j) {
    final evs = (j['events'] as List).cast<Map<String, dynamic>>();
    return Scenario(
      id: j['id'] as String,
      label: j['label'] as String? ?? j['id'] as String,
      category: j['category'] as String? ?? 'unknown',
      expected: (j['expected'] as Map?)?.cast<String, dynamic>() ?? const {},
      events: [
        for (int i = 0; i < evs.length; i++)
          ScheduledEvent(
            offset: Duration(seconds: (evs[i]['t_seconds'] as num).toInt()),
            payload: evs[i],
            index: i,
          ),
      ],
    );
  }
}

@immutable
class ScheduledEvent {
  const ScheduledEvent({
    required this.offset,
    required this.payload,
    required this.index,
  });

  final Duration offset;
  final Map<String, dynamic> payload;
  final int index;
}

@immutable
class ScenarioState {
  const ScenarioState({
    this.playing,
    this.progress = 0.0,
    this.completed = const [],
    this.pendingUserTransaction,
  });

  final Scenario? playing;
  final double progress;
  final List<String> completed;

  /// A transaction event that the scenario is *scripting* but has NOT
  /// auto-ingested. Set when the scheduled timer for the txn fires;
  /// cleared when the user completes or cancels the transfer via the
  /// Bank UI. Used for both the "Next step" hint on Home and to
  /// pre-fill the Transfer form.
  final TransactionEvent? pendingUserTransaction;

  ScenarioState copyWith({
    Scenario? playing,
    bool clearPlaying = false,
    double? progress,
    List<String>? completed,
    TransactionEvent? pendingUserTransaction,
    bool clearPendingUserTransaction = false,
  }) {
    return ScenarioState(
      playing: clearPlaying ? null : (playing ?? this.playing),
      progress: progress ?? this.progress,
      completed: completed ?? this.completed,
      pendingUserTransaction: clearPendingUserTransaction
          ? null
          : (pendingUserTransaction ?? this.pendingUserTransaction),
    );
  }
}

class ScenarioEngine extends Notifier<ScenarioState> {
  final List<Timer> _timers = [];
  final Map<String, Scenario> _cache = {};
  bool _loadedIndex = false;

  @override
  ScenarioState build() {
    ref.onDispose(_cancelAll);
    return const ScenarioState();
  }

  Future<List<Scenario>> listScenarios() async {
    if (!_loadedIndex) await _loadAllAssets();
    final list = _cache.values.toList()
      ..sort((a, b) => a.id.compareTo(b.id));
    return list;
  }

  Future<Scenario?> load(String id) async {
    if (_cache.containsKey(id)) return _cache[id];
    if (!_loadedIndex) {
      await _loadAllAssets();
    }
    return _cache[id];
  }

  Future<void> _loadAllAssets() async {
    _loadedIndex = true;
    try {
      final manifest = await AssetManifest.loadFromAssetBundle(rootBundle);
      final keys = manifest
          .listAssets()
          .where((k) => k.startsWith('assets/scenarios/') && k.endsWith('.json'))
          .toList();
      dev.log('scenario manifest: ${keys.length} entries', name: 'scenario');
      for (final k in keys) {
        try {
          final raw = await rootBundle.loadString(k);
          final s = Scenario.fromJson(jsonDecode(raw) as Map<String, dynamic>);
          _cache[s.id] = s;
        } catch (e) {
          dev.log('Failed to parse scenario $k: $e', name: 'scenario');
        }
      }
    } catch (e) {
      dev.log('Failed to load scenario manifest: $e', name: 'scenario');
    }
  }

  Future<void> play(String id) async {
    _cancelAll();
    final scenario = await load(id);
    if (scenario == null) {
      dev.log('Scenario not found: $id', name: 'scenario');
      return;
    }
    state = state.copyWith(
      playing: scenario,
      progress: 0,
      clearPendingUserTransaction: true,
    );
    dev.log('[scenario] ▶ ${scenario.id} — ${scenario.label}', name: 'scenario');
    final base = DateTime.now();
    final ctx = ref.read(contextAgentProvider.notifier);
    final totalMs = scenario.events.isEmpty
        ? 1
        : scenario.events.last.offset.inMilliseconds + 1;
    for (final s in scenario.events) {
      final t = Timer(s.offset, () async {
        final ts = base.add(s.offset);
        final event = eventFromJson(
          s.payload,
          ts,
          '${scenario.id}_${s.index}',
        );
        final isTxn = event is TransactionEvent;
        if (isTxn) {
          // Do NOT auto-ingest. Expose it as a "next step" so the demo
          // operator walks through the Bank → Transfer flow manually
          // for better storytelling.
          dev.log(
            '[scenario] @${s.offset.inSeconds}s ⏸ await user txn '
            '(HKD ${event.amountHkd} → ${event.toName})',
            name: 'scenario',
          );
          state = state.copyWith(pendingUserTransaction: event);
        } else {
          dev.log(
            '[scenario] @${s.offset.inSeconds}s → ${event.kind.name}',
            name: 'scenario',
          );
          await ctx.ingest(event);
        }
        final progress = (s.offset.inMilliseconds + 1) / totalMs;
        state = state.copyWith(progress: progress.clamp(0.0, 1.0));
        if (s.index == scenario.events.length - 1) {
          state = state.copyWith(
            progress: 1.0,
            completed: [...state.completed, scenario.id],
          );
          Timer(const Duration(seconds: 2), () {
            // Keep pending txn alive even after playback ends — the
            // user may not have completed it yet.
            if (state.playing?.id == scenario.id &&
                state.pendingUserTransaction == null) {
              state = state.copyWith(clearPlaying: true);
            }
          });
        }
      });
      _timers.add(t);
    }
  }

  /// Called by the Transfer screen when the user has (1) submitted or
  /// (2) cancelled the scripted transaction. Clears the pending hint
  /// so Home no longer shows the "Next step" card.
  void resolvePendingTransaction() {
    state = state.copyWith(clearPendingUserTransaction: true);
    // If playback already finished, auto-clear the playing scenario
    // now that the user has handled the last step.
    if (state.progress >= 1.0) {
      state = state.copyWith(clearPlaying: true);
    }
  }

  void stop() {
    _cancelAll();
    state = state.copyWith(
      clearPlaying: true,
      progress: 0,
      clearPendingUserTransaction: true,
    );
  }

  void _cancelAll() {
    for (final t in _timers) {
      t.cancel();
    }
    _timers.clear();
  }
}

final scenarioEngineProvider =
    NotifierProvider<ScenarioEngine, ScenarioState>(ScenarioEngine.new);
