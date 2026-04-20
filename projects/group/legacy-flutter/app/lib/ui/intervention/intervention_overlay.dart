import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../agents/intervention_agent.dart';
import '../../core/router.dart';
import '../../core/theme.dart';

bool _overlayVisible = false;

void showInterventionOverlay(BuildContext context, WidgetRef ref) {
  if (_overlayVisible) return;
  _overlayVisible = true;
  final navigator =
      rootNavigatorKey.currentState ?? Navigator.of(context, rootNavigator: true);
  navigator
      .push(MaterialPageRoute(
        fullscreenDialog: true,
        builder: (_) => const _InterventionSheet(),
      ))
      .whenComplete(() => _overlayVisible = false);
}

class _InterventionSheet extends ConsumerStatefulWidget {
  const _InterventionSheet();

  @override
  ConsumerState<_InterventionSheet> createState() =>
      _InterventionSheetState();
}

class _InterventionSheetState extends ConsumerState<_InterventionSheet> {
  Timer? _timer;
  int _remaining = 0;

  @override
  void initState() {
    super.initState();
    final action = ref.read(interventionAgentProvider).pending;
    if (action != null && action.cooldownSeconds > 0) {
      _remaining =
          action.level == InterventionLevel.delay ? 60 : action.cooldownSeconds;
      _timer = Timer.periodic(const Duration(seconds: 1), (t) {
        setState(() {
          _remaining = (_remaining - 1).clamp(0, 1 << 30);
          if (_remaining == 0) t.cancel();
        });
      });
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final action = ref.watch(interventionAgentProvider).pending;
    if (action == null) {
      return const SizedBox.shrink();
    }
    final color = RiskPalette.forRisk(action.risk);
    final isDelay = action.level == InterventionLevel.delay;
    return PopScope(
      canPop: false,
      child: Scaffold(
        backgroundColor: const Color(0xFFFDF3F2),
        body: SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      isDelay ? Icons.schedule : Icons.warning_amber_rounded,
                      color: color,
                      size: 40,
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        isDelay ? '24-hour hold suggested' : 'Pause a moment',
                        style: Theme.of(context)
                            .textTheme
                            .headlineMedium
                            ?.copyWith(fontWeight: FontWeight.w800),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),
                Container(
                  padding: const EdgeInsets.symmetric(
                      horizontal: 12, vertical: 6),
                  decoration: BoxDecoration(
                    color: color.withAlpha(30),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: Text(
                    'Guardian risk ${(action.risk * 100).toStringAsFixed(0)}% · '
                    '${RiskPalette.labelFor(action.risk)}',
                    style: TextStyle(
                      color: color,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                ),
                const SizedBox(height: 24),
                Text(
                  action.headline,
                  style: Theme.of(context).textTheme.titleLarge,
                ),
                const SizedBox(height: 12),
                Text(
                  action.body,
                  style: Theme.of(context)
                      .textTheme
                      .bodyLarge
                      ?.copyWith(height: 1.5),
                ),
                const Spacer(),
                if (_remaining > 0 && !isDelay)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Text(
                      'You can continue in ${_remaining}s — use this time to verify.',
                      style: TextStyle(color: Colors.grey.shade700),
                    ),
                  ),
                if (isDelay)
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(12),
                      border: Border.all(color: color.withAlpha(120)),
                    ),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          'Your trusted contact will be notified',
                          style: Theme.of(context)
                              .textTheme
                              .titleMedium
                              ?.copyWith(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 6),
                        const Text(
                          'Son (David Wong) — +852 6xxx xxxx. You can continue '
                          'this transfer in 24 hours after a family check-in.',
                        ),
                      ],
                    ),
                  ),
                const SizedBox(height: 16),
                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        style: FilledButton.styleFrom(
                          backgroundColor: color,
                          foregroundColor: Colors.white,
                        ),
                        onPressed: () {
                          ref
                              .read(interventionAgentProvider.notifier)
                              .resolvePending();
                          Navigator.of(context).pop();
                        },
                        icon: const Icon(Icons.phone_in_talk),
                        label: const Text('Call my son'),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: (_remaining > 0 && !isDelay) || isDelay
                            ? null
                            : () {
                                ref
                                    .read(interventionAgentProvider.notifier)
                                    .overridePending();
                                Navigator.of(context).pop();
                              },
                        child: Text(isDelay
                            ? 'Locked for 24h'
                            : 'I am sure, proceed (PIN)'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
