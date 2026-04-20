import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../agents/intervention_agent.dart';
import '../agents/risk_agent.dart';
import '../agents/user_settings.dart';
import '../core/theme.dart';
import '../data/event_log.dart';
import '../scenarios/events.dart';
import '../scenarios/scenario_engine.dart';
import 'intervention/intervention_overlay.dart';
import 'status_bar.dart';

class HomeScreen extends ConsumerWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final scenarioState = ref.watch(scenarioEngineProvider);
    final events = ref.watch(eventLogProvider);
    final assessments = ref.watch(riskAgentProvider);
    final intervention = ref.watch(interventionAgentProvider);
    final userSettings = ref.watch(userSettingsProvider);

    ref.listen<InterventionState>(interventionAgentProvider, (_, next) {
      final p = next.pending;
      if (p != null &&
          (p.level == InterventionLevel.fullScreen ||
              p.level == InterventionLevel.delay)) {
        showInterventionOverlay(context, ref);
      }
    });

    final topRisk = assessments.isEmpty
        ? 0.0
        : assessments
            .map((a) => a.finalRisk)
            .reduce((a, b) => a > b ? a : b);

    return Scaffold(
      backgroundColor: const Color(0xFFF4F6F9),
      body: SafeArea(
        child: Column(
          children: [
            const GuardianStatusBar(),
            if (intervention.ambient != null)
              _AmbientBanner(action: intervention.ambient!),
            Expanded(
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 720),
                  child: CustomScrollView(
                    slivers: [
                      SliverPadding(
                        padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
                        sliver: SliverToBoxAdapter(
                          child: _Greeting(
                            topRisk: topRisk,
                            holderName: userSettings.accountHolder,
                          ),
                        ),
                      ),
                      if (scenarioState.pendingUserTransaction != null)
                        SliverPadding(
                          padding:
                              const EdgeInsets.fromLTRB(20, 16, 20, 0),
                          sliver: SliverToBoxAdapter(
                            child: _PendingTxnCard(
                              txn: scenarioState.pendingUserTransaction!,
                            ),
                          ),
                        ),
                      SliverPadding(
                        padding: const EdgeInsets.fromLTRB(20, 16, 20, 0),
                        sliver: SliverToBoxAdapter(
                          child: _AppTiles(),
                        ),
                      ),
                      SliverPadding(
                        padding: const EdgeInsets.fromLTRB(20, 16, 20, 8),
                        sliver: SliverToBoxAdapter(
                          child: _ScenarioPanel(state: scenarioState),
                        ),
                      ),
                      SliverPadding(
                        padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
                        sliver: SliverToBoxAdapter(
                          child: _RecentActivity(
                              events: events.reversed.take(6).toList()),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _Greeting extends StatelessWidget {
  const _Greeting({required this.topRisk, required this.holderName});
  final double topRisk;
  final String holderName;

  @override
  Widget build(BuildContext context) {
    final color = RiskPalette.forRisk(topRisk);
    final label = RiskPalette.labelFor(topRisk);
    final hour = DateTime.now().hour;
    final period = hour < 12
        ? 'Good morning'
        : (hour < 18 ? 'Good afternoon' : 'Good evening');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          '$period, $holderName',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Container(
              width: 12,
              height: 12,
              decoration: BoxDecoration(
                color: color,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 8),
            Text(
              'Guardian is on · $label',
              style: Theme.of(context).textTheme.bodyLarge?.copyWith(
                    color: Colors.black87,
                    fontWeight: FontWeight.w600,
                  ),
            ),
          ],
        ),
      ],
    );
  }
}

class _PendingTxnCard extends StatelessWidget {
  const _PendingTxnCard({required this.txn});
  final TransactionEvent txn;

  @override
  Widget build(BuildContext context) {
    final fmt = NumberFormat.currency(locale: 'en_HK', symbol: 'HK\$ ');
    const accent = Color(0xFFE37400);
    return Material(
      color: const Color(0xFFFFF8EB),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(14),
        side: const BorderSide(color: Color(0xFFE0B878)),
      ),
      child: InkWell(
        borderRadius: BorderRadius.circular(14),
        onTap: () => context.go('/bank/transfer'),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: accent.withAlpha(30),
                  shape: BoxShape.circle,
                ),
                child: const Icon(Icons.pan_tool_outlined, color: accent),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'Next step — the caller is pressuring you',
                      style: TextStyle(
                        color: accent,
                        fontWeight: FontWeight.w700,
                        fontSize: 13,
                        letterSpacing: 0.3,
                      ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Transfer ${fmt.format(txn.amountHkd)} to ${txn.toName}',
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 2),
                    Text(
                      'Tap Bank → Transfer to see what Guardian does.',
                      style: TextStyle(
                        color: Colors.brown.shade800,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: accent),
            ],
          ),
        ),
      ),
    );
  }
}

class _AppTiles extends StatelessWidget {
  @override
  Widget build(BuildContext context) {
    final tiles = <_AppTileData>[
      _AppTileData(
        icon: Icons.account_balance,
        label: 'Bank',
        subtitle: 'Balance & transfers',
        color: const Color(0xFF005A9C),
        onTap: () => context.go('/bank'),
      ),
      _AppTileData(
        icon: Icons.sms,
        label: 'Messages',
        subtitle: 'SMS inbox',
        color: const Color(0xFF1E8E3E),
        onTap: () => context.go('/sms'),
      ),
      _AppTileData(
        icon: Icons.chat,
        label: 'Chat',
        subtitle: 'Family & contacts',
        color: const Color(0xFF8E24AA),
        onTap: () => context.go('/chat'),
      ),
      _AppTileData(
        icon: Icons.shield_outlined,
        label: 'Audit',
        subtitle: 'Decision log',
        color: const Color(0xFF455A64),
        onTap: () => context.go('/audit'),
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        // Wider windows (desktop) get 2 columns; very narrow (phone) stays
        // 1 column so each tile has room to breathe.
        final crossAxis = constraints.maxWidth >= 520 ? 2 : 1;
        return GridView.count(
          crossAxisCount: crossAxis,
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          mainAxisSpacing: 12,
          crossAxisSpacing: 12,
          // ~112 px tall tiles regardless of column count.
          childAspectRatio: crossAxis == 2 ? 2.9 : 5.6,
          children: [for (final t in tiles) _AppTile(data: t)],
        );
      },
    );
  }
}

class _AppTileData {
  _AppTileData({
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.color,
    required this.onTap,
  });
  final IconData icon;
  final String label;
  final String subtitle;
  final Color color;
  final VoidCallback onTap;
}

class _AppTile extends StatelessWidget {
  const _AppTile({required this.data});
  final _AppTileData data;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: InkWell(
        onTap: data.onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          child: Row(
            children: [
              CircleAvatar(
                radius: 22,
                backgroundColor: data.color.withAlpha(30),
                child: Icon(data.icon, color: data.color, size: 24),
              ),
              const SizedBox(width: 14),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  mainAxisAlignment: MainAxisAlignment.center,
                  children: [
                    Text(
                      data.label,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      data.subtitle,
                      maxLines: 1,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(
                        color: Colors.grey.shade600,
                        fontSize: 13,
                      ),
                    ),
                  ],
                ),
              ),
              Icon(
                Icons.chevron_right_rounded,
                color: Colors.grey.shade400,
                size: 24,
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ScenarioPanel extends ConsumerStatefulWidget {
  const _ScenarioPanel({required this.state});
  final ScenarioState state;

  @override
  ConsumerState<_ScenarioPanel> createState() => _ScenarioPanelState();
}

class _ScenarioPanelState extends ConsumerState<_ScenarioPanel> {
  late Future<List<Scenario>> _scenarios;

  @override
  void initState() {
    super.initState();
    _scenarios = ref.read(scenarioEngineProvider.notifier).listScenarios();
  }

  @override
  Widget build(BuildContext context) {
    return FutureBuilder<List<Scenario>>(
      future: _scenarios,
      builder: (context, snap) {
        final scenarios = snap.data ?? const <Scenario>[];
        return Card(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(Icons.play_circle_fill,
                        color: Color(0xFF005A9C), size: 28),
                    const SizedBox(width: 8),
                    Text('Demo scenarios',
                        style: Theme.of(context).textTheme.titleLarge),
                    const Spacer(),
                    if (widget.state.playing != null)
                      OutlinedButton.icon(
                        onPressed: () =>
                            ref.read(scenarioEngineProvider.notifier).stop(),
                        icon: const Icon(Icons.stop_circle_outlined),
                        label: const Text('Stop'),
                      ),
                  ],
                ),
                const SizedBox(height: 8),
                Text(
                  'Play a scripted scam or benign scenario. Events flow through '
                  'the Guardian agents in real time.',
                  style: Theme.of(context).textTheme.bodyMedium,
                ),
                const SizedBox(height: 12),
                if (widget.state.playing != null) ...[
                  LinearProgressIndicator(value: widget.state.progress),
                  const SizedBox(height: 8),
                  Text('Playing: ${widget.state.playing!.label}'),
                  const SizedBox(height: 12),
                ],
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    for (final s in scenarios)
                      FilledButton.tonal(
                        onPressed: widget.state.playing != null
                            ? null
                            : () => ref
                                .read(scenarioEngineProvider.notifier)
                                .play(s.id),
                        style: FilledButton.styleFrom(
                          minimumSize: const Size(64, 48),
                          textStyle: const TextStyle(fontSize: 15),
                        ),
                        child: Text(s.id.replaceAll('_', ' ')),
                      ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }
}

class _RecentActivity extends StatelessWidget {
  const _RecentActivity({required this.events});
  final List<EventLogEntry> events;

  @override
  Widget build(BuildContext context) {
    if (events.isEmpty) return const SizedBox.shrink();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Recent activity',
                style: Theme.of(context).textTheme.titleLarge),
            const SizedBox(height: 12),
            for (final e in events) _ActivityRow(entry: e),
          ],
        ),
      ),
    );
  }
}

class _ActivityRow extends StatelessWidget {
  const _ActivityRow({required this.entry});
  final EventLogEntry entry;

  @override
  Widget build(BuildContext context) {
    final icon = switch (entry.event) {
      CallEvent() => Icons.call,
      SmsEvent() => Icons.sms,
      ChatEvent() => Icons.chat_bubble_outline,
      TransactionEvent() => Icons.payments,
    };
    final title = switch (entry.event) {
      CallEvent(from: final f) => 'Call from $f',
      SmsEvent(from: final f) => 'SMS from $f',
      ChatEvent(contact: final c) => 'Chat: $c',
      TransactionEvent(toName: final t, amountHkd: final a) =>
        'Transfer HKD ${a.toStringAsFixed(0)} → $t',
    };
    final subtitle = switch (entry.event) {
      CallEvent(transcript: final t) => t,
      SmsEvent(body: final b) => b,
      ChatEvent(body: final b) => b,
      TransactionEvent() => 'New payee transfer',
    };
    final risk = entry.riskScore;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Row(
        children: [
          CircleAvatar(
            radius: 20,
            backgroundColor: Colors.grey.shade200,
            child: Icon(icon, color: Colors.black87),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title,
                    style: const TextStyle(fontWeight: FontWeight.w600)),
                Text(
                  subtitle,
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                  style: TextStyle(color: Colors.grey.shade700),
                ),
              ],
            ),
          ),
          if (risk != null)
            Container(
              padding: const EdgeInsets.symmetric(
                  horizontal: 10, vertical: 4),
              decoration: BoxDecoration(
                color: RiskPalette.forRisk(risk).withAlpha(30),
                borderRadius: BorderRadius.circular(8),
              ),
              child: Text(
                '${(risk * 100).toStringAsFixed(0)}%',
                style: TextStyle(
                  color: RiskPalette.forRisk(risk),
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
        ],
      ),
    );
  }
}

class _AmbientBanner extends ConsumerWidget {
  const _AmbientBanner({required this.action});
  final InterventionAction action;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final color = RiskPalette.forRisk(action.risk);
    return Material(
      color: color.withAlpha(25),
      child: InkWell(
        onTap: () => context.go('/audit'),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 14),
          child: Row(
            children: [
              Icon(Icons.warning_amber_rounded, color: color, size: 28),
              const SizedBox(width: 12),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      action.headline,
                      style: TextStyle(
                          color: color, fontWeight: FontWeight.w700),
                    ),
                    const SizedBox(height: 2),
                    const Text(
                      'Tap to see why',
                      style: TextStyle(fontSize: 14, color: Colors.black54),
                    ),
                  ],
                ),
              ),
              IconButton(
                onPressed: () => ref
                    .read(interventionAgentProvider.notifier)
                    .dismissAmbient(),
                icon: const Icon(Icons.close),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
