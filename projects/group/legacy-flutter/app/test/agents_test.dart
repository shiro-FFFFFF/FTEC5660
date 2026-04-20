import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:guardian/agents/context_agent.dart';
import 'package:guardian/agents/intervention_agent.dart';
import 'package:guardian/agents/risk_agent.dart';
import 'package:guardian/data/scam_db.dart';
import 'package:guardian/llm/heuristic_runtime.dart';
import 'package:guardian/llm/llm_runtime.dart';
import 'package:guardian/scenarios/events.dart';
import 'package:riverpod/riverpod.dart';

ScamDatabase _loadDb() {
  // Tests run with CWD at the Flutter package root.
  final file = File('assets/scam_db.csv');
  return ScamDatabase.fromCsv(file.readAsStringSync());
}

ProviderContainer _container() {
  // Override the LLM runtime with the deterministic heuristic so tests
  // don't depend on a running Ollama server (which would be both slow
  // and non-reproducible in CI).
  return ProviderContainer(
    overrides: [
      scamDatabaseProvider.overrideWithValue(_loadDb()),
      llmRuntimeProvider.overrideWithValue(HeuristicLlmRuntime()),
    ],
  );
}

void main() {
  group('RiskAgent rule scorer', () {
    test('benign SMS scores low', () async {
      final c = _container();
      addTearDown(c.dispose);
      await c
          .read(contextAgentProvider.notifier)
          .ingest(
            SmsEvent(
              id: 'x1',
              timestamp: DateTime.now(),
              from: 'CLP',
              body: 'Your electricity bill of HKD 412 is due on 25 Apr.',
            ),
          );
      final a = c.read(riskAgentProvider).single;
      expect(a.finalRisk, lessThan(0.3));
    });

    test('phishing SMS with known bad domain scores high', () async {
      final c = _container();
      addTearDown(c.dispose);
      await c
          .read(contextAgentProvider.notifier)
          .ingest(
            SmsEvent(
              id: 'x2',
              timestamp: DateTime.now(),
              from: 'HSBC-Secure',
              body:
                  'URGENT: Suspicious login. Verify at http://hsbc-hk.verify-id.top/',
            ),
          );
      final a = c.read(riskAgentProvider).single;
      expect(a.finalRisk, greaterThanOrEqualTo(0.6));
    });

    test(
      'transfer to new payee right after scam call escalates to delay',
      () async {
        final c = _container();
        addTearDown(c.dispose);
        final now = DateTime.now();
        await c
            .read(contextAgentProvider.notifier)
            .ingest(
              CallEvent(
                id: 'c1',
                timestamp: now,
                from: '+852 0000 0001',
                transcript:
                    'Police cybercrime unit. Transfer your funds to a secure holding account.',
              ),
            );
        await c
            .read(contextAgentProvider.notifier)
            .ingest(
              TransactionEvent(
                id: 't1',
                timestamp: now.add(const Duration(seconds: 60)),
                amountHkd: 50000,
                toName: 'Unknown Ltd',
                toAccount: '012-345678-999',
                newRecipient: true,
              ),
            );
        final interventions = c.read(interventionAgentProvider).history;
        expect(interventions, isNotEmpty);
        final last = interventions.last;
        expect(last.level, InterventionLevel.delay);
        expect(last.risk, greaterThanOrEqualTo(0.85));
        final txnAssessment = c.read(riskAgentProvider).last;
        expect(txnAssessment.reviewerRisk, isNotNull);
        expect(txnAssessment.consensus, 'aligned');
        expect(
          txnAssessment.toolTrace.any(
            (s) => s.tool == 'orchestrator_second_opinion',
          ),
          isTrue,
        );
      },
    );
  });

  group('temporal risk memory', () {
    test('later chat message inherits risk from earlier in same thread', () async {
      final c = _container();
      addTearDown(c.dispose);
      final now = DateTime.now();
      await c
          .read(contextAgentProvider.notifier)
          .ingest(
            ChatEvent(
              id: 'ch1',
              timestamp: now,
              contact: 'Emily',
              body:
                  'VIP tip from my uncle — guaranteed return 40% in two weeks.',
            ),
          );
      final firstRisk = c.read(riskAgentProvider).last.finalRisk;
      await c
          .read(contextAgentProvider.notifier)
          .ingest(
            ChatEvent(
              id: 'ch2',
              timestamp: now.add(const Duration(minutes: 5)),
              contact: 'Emily',
              body: "Please don't tell your family. Trust me.",
            ),
          );
      final secondRisk = c.read(riskAgentProvider).last.finalRisk;
      // First message already flags investment tactics; second gets temporal bump
      // (base ~0.35 from isolation keyword, lifted to >= 0.55 by scam_thread).
      expect(firstRisk, greaterThanOrEqualTo(0.5));
      expect(secondRisk, greaterThanOrEqualTo(0.55));
      final scamThread = c
          .read(riskAgentProvider)
          .last
          .contributions
          .where((c) => c.feature == 'scam_thread')
          .toList();
      expect(scamThread, isNotEmpty);
    });
  });
}
