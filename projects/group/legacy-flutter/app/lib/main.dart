import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/router.dart';
import 'core/theme.dart';
import 'data/scam_db.dart';
import 'data/scam_db_loader.dart';
import 'llm/llm_runtime.dart';
import 'scenarios/scenario_engine.dart';

const String _autoplay = String.fromEnvironment('AUTOPLAY');

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  final db = await loadScamDatabaseFromAssets();
  runApp(ProviderScope(
    overrides: [scamDatabaseProvider.overrideWithValue(db)],
    child: const GuardianApp(),
  ));
}

class GuardianApp extends ConsumerStatefulWidget {
  const GuardianApp({super.key});

  @override
  ConsumerState<GuardianApp> createState() => _GuardianAppState();
}

class _GuardianAppState extends ConsumerState<GuardianApp> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) async {
      // Kick off LLM runtime detection / warmup so the status bar resolves.
      // ignore: unused_result
      ref.read(llmStatusProvider);
      if (_autoplay.isNotEmpty) {
        await Future.delayed(const Duration(milliseconds: 800));
        await ref.read(scenarioEngineProvider.notifier).play(_autoplay);
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'Guardian — Decision Security',
      debugShowCheckedModeBanner: false,
      theme: guardianTheme,
      routerConfig: router,
    );
  }
}
