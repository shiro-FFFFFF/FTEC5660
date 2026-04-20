import 'dart:developer' as dev;

import 'package:meta/meta.dart';
import 'package:riverpod/riverpod.dart';

import '../agents/context_agent.dart';
import '../agents/risk_agent.dart';
import 'heuristic_runtime.dart';
import 'ollama_runtime.dart';
import 'tools.dart';

@immutable
class LlmRiskOutput {
  const LlmRiskOutput({
    required this.risk,
    required this.tactics,
    required this.reasons,
    required this.confidence,
    required this.source,
    this.trace = const [],
  });

  final double risk;
  final List<String> tactics;
  final List<String> reasons;
  final double confidence;
  final String source;

  /// Ordered record of tools the LLM invoked to reach this verdict.
  /// Empty if the runtime did a single-shot classification (e.g.
  /// heuristic fallback, or a small model that ignored tool calls).
  final List<ToolCallStep> trace;
}

abstract class LlmRuntime {
  Future<LlmRiskOutput> scoreRisk({
    required ContextSnapshot snapshot,
    required double ruleScore,
    required List<RuleScoreContribution> ruleContributions,
    ToolRegistry? tools,
  });

  Future<String> explain({
    required ContextSnapshot snapshot,
    required double finalRisk,
  });

  Future<void> warmup();
  bool get ready;
  String get name;
}

class SmartLlmRuntime implements LlmRuntime {
  SmartLlmRuntime({LlmRuntime? primary, LlmRuntime? fallback})
      : _primary = primary ?? OllamaLlmRuntime(),
        _fallback = fallback ?? HeuristicLlmRuntime();

  final LlmRuntime _primary;
  final LlmRuntime _fallback;
  bool? _primaryOk;

  Future<bool> _ensurePrimary() async {
    if (_primaryOk != null) return _primaryOk!;
    final p = _primary;
    if (p is OllamaLlmRuntime) {
      _primaryOk = await p.isReachable();
      if (_primaryOk!) {
        try {
          await p.warmup();
        } catch (e) {
          dev.log('primary warmup failed: $e', name: 'llm');
          _primaryOk = false;
        }
      }
    } else {
      _primaryOk = true;
      try {
        await p.warmup();
      } catch (_) {
        _primaryOk = false;
      }
    }
    dev.log('llm runtime: ${_primaryOk! ? _primary.name : _fallback.name}',
        name: 'llm');
    return _primaryOk!;
  }

  @override
  bool get ready => _primaryOk != null;

  @override
  String get name {
    if (_primaryOk == true) return _primary.name;
    if (_primaryOk == false) return _fallback.name;
    return 'detecting…';
  }

  @override
  Future<void> warmup() => _ensurePrimary();

  @override
  Future<LlmRiskOutput> scoreRisk({
    required ContextSnapshot snapshot,
    required double ruleScore,
    required List<RuleScoreContribution> ruleContributions,
    ToolRegistry? tools,
  }) async {
    if (await _ensurePrimary()) {
      try {
        return await _primary.scoreRisk(
          snapshot: snapshot,
          ruleScore: ruleScore,
          ruleContributions: ruleContributions,
          tools: tools,
        );
      } catch (e) {
        dev.log('primary scoreRisk failed, falling back: $e', name: 'llm');
        _primaryOk = false;
      }
    }
    return _fallback.scoreRisk(
      snapshot: snapshot,
      ruleScore: ruleScore,
      ruleContributions: ruleContributions,
      tools: tools,
    );
  }

  @override
  Future<String> explain({
    required ContextSnapshot snapshot,
    required double finalRisk,
  }) async {
    if (await _ensurePrimary()) {
      try {
        return await _primary.explain(
          snapshot: snapshot,
          finalRisk: finalRisk,
        );
      } catch (e) {
        dev.log('primary explain failed: $e', name: 'llm');
      }
    }
    return _fallback.explain(snapshot: snapshot, finalRisk: finalRisk);
  }
}

final llmRuntimeProvider = Provider<LlmRuntime>((ref) {
  return SmartLlmRuntime();
});

final llmStatusProvider = FutureProvider<String>((ref) async {
  final llm = ref.read(llmRuntimeProvider);
  await llm.warmup();
  return llm.name;
});
