import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:guardian/agents/context_agent.dart';
import 'package:guardian/agents/intervention_agent.dart';
import 'package:guardian/agents/risk_agent.dart';
import 'package:guardian/data/scam_db.dart';
import 'package:guardian/scenarios/events.dart';
import 'package:riverpod/riverpod.dart';

Future<void> main(List<String> args) async {
  final csv = File('assets/scam_db.csv').readAsStringSync();
  final db = ScamDatabase.fromCsv(csv);

  final scenariosDir = Directory('assets/scenarios');
  if (!scenariosDir.existsSync()) {
    stderr.writeln('No scenarios in ${scenariosDir.path}. '
        'Run `just sync-scenarios` first.');
    exit(2);
  }
  final files = scenariosDir
      .listSync()
      .whereType<File>()
      .where((f) => f.path.endsWith('.json'))
      .toList()
    ..sort((a, b) => a.path.compareTo(b.path));

  final rows = <_Row>[];
  for (final f in files) {
    final scenario =
        jsonDecode(f.readAsStringSync()) as Map<String, dynamic>;
    final row = await _runScenario(scenario, db);
    rows.add(row);
  }

  _printTable(rows);
  _writeJson(rows);
}

Future<_Row> _runScenario(
  Map<String, dynamic> scenario,
  ScamDatabase db,
) async {
  final container = ProviderContainer(overrides: [
    scamDatabaseProvider.overrideWithValue(db),
  ]);
  try {
    final base = DateTime.now();
    final events = (scenario['events'] as List).cast<Map<String, dynamic>>();
    for (var i = 0; i < events.length; i++) {
      final e = events[i];
      final ts = base.add(
        Duration(seconds: (e['t_seconds'] as num).toInt()),
      );
      final id = '${scenario['id']}_$i';
      final event = eventFromJson(e, ts, id);
      await container.read(contextAgentProvider.notifier).ingest(event);
    }
    final assessments = container.read(riskAgentProvider);
    final intervention = container.read(interventionAgentProvider);
    final maxRisk = assessments.isEmpty
        ? 0.0
        : assessments
            .map((a) => a.finalRisk)
            .reduce((a, b) => a > b ? a : b);
    final actions = intervention.history;
    final topLevel = actions.isEmpty
        ? InterventionLevel.none
        : actions
            .map((a) => a.level)
            .reduce((a, b) => a.index > b.index ? a : b);
    final expected =
        (scenario['expected'] as Map?)?.cast<String, dynamic>() ?? const {};
    final expMin = (expected['min_risk'] as num?)?.toDouble() ?? 0.0;
    final expMax = (expected['max_risk'] as num?)?.toDouble() ?? 1.0;
    final expIntervention =
        expected['intervention'] as String? ?? 'none';
    final pass = maxRisk >= expMin - 0.05 &&
        maxRisk <= expMax + 0.05 &&
        _compat(topLevel, expIntervention);
    return _Row(
      id: scenario['id'] as String,
      category: scenario['category'] as String? ?? 'unknown',
      maxRisk: maxRisk,
      expectedMin: expMin,
      expectedMax: expMax,
      actualIntervention: topLevel.name,
      expectedIntervention: expIntervention,
      pass: pass,
      assessments: assessments.map((a) => a.toJson()).toList(),
    );
  } finally {
    container.dispose();
  }
}

bool _compat(InterventionLevel actual, String expected) {
  switch (expected) {
    case 'none':
      return actual == InterventionLevel.none;
    case 'banner':
      return actual == InterventionLevel.banner;
    case 'full_screen':
      return actual == InterventionLevel.fullScreen ||
          actual == InterventionLevel.delay;
    case 'full_screen_delay':
      return actual == InterventionLevel.delay;
    default:
      return true;
  }
}

void _printTable(List<_Row> rows) {
  final header =
      '| scenario                        | cat           | risk  |'
      ' expected        | action        | exp action       | pass |';
  final sep = '|${'-' * (header.length - 2)}|';
  stdout.writeln(header);
  stdout.writeln(sep);
  for (final r in rows) {
    stdout.writeln(
      '| ${r.id.padRight(31)} '
      '| ${r.category.padRight(13)} '
      '| ${r.maxRisk.toStringAsFixed(2).padLeft(5)} '
      '| [${r.expectedMin.toStringAsFixed(2)}, ${r.expectedMax.toStringAsFixed(2)}] '
      '| ${r.actualIntervention.padRight(13)} '
      '| ${r.expectedIntervention.padRight(16)} '
      '| ${r.pass ? "✓" : "✗"}    |',
    );
  }
  final passed = rows.where((r) => r.pass).length;
  stdout.writeln('');
  stdout.writeln('Passed: $passed / ${rows.length}');
}

void _writeJson(List<_Row> rows) {
  final dir = Directory('../reports');
  if (!dir.existsSync()) dir.createSync(recursive: true);
  final ts = DateTime.now().toIso8601String().replaceAll(':', '-');
  final out = File('${dir.path}/eval-$ts.json');
  out.writeAsStringSync(
      const JsonEncoder.withIndent('  ').convert({
    'generated_at': DateTime.now().toIso8601String(),
    'rows': [for (final r in rows) r.toJson()],
  }));
  stdout.writeln('Wrote ${out.path}');
}

class _Row {
  _Row({
    required this.id,
    required this.category,
    required this.maxRisk,
    required this.expectedMin,
    required this.expectedMax,
    required this.actualIntervention,
    required this.expectedIntervention,
    required this.pass,
    required this.assessments,
  });
  final String id;
  final String category;
  final double maxRisk;
  final double expectedMin;
  final double expectedMax;
  final String actualIntervention;
  final String expectedIntervention;
  final bool pass;
  final List<Map<String, dynamic>> assessments;

  Map<String, dynamic> toJson() => {
        'id': id,
        'category': category,
        'max_risk': maxRisk,
        'expected_min': expectedMin,
        'expected_max': expectedMax,
        'actual_intervention': actualIntervention,
        'expected_intervention': expectedIntervention,
        'pass': pass,
        'assessments': assessments,
      };
}
