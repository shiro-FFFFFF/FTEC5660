import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../core/theme.dart';
import '../../data/event_log.dart';
import '../../scenarios/events.dart';

class SmsInboxScreen extends ConsumerWidget {
  const SmsInboxScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final entries = ref
        .watch(eventLogProvider)
        .where((e) => e.event is SmsEvent)
        .toList()
        .reversed
        .toList();
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        title: const Text('Messages'),
      ),
      body: entries.isEmpty
          ? const _Empty()
          : ListView.separated(
              itemCount: entries.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (context, i) {
                final e = entries[i];
                final sms = e.event as SmsEvent;
                final risk = e.riskScore ?? 0;
                return ListTile(
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                  leading: CircleAvatar(
                    backgroundColor: RiskPalette.forRisk(risk).withAlpha(30),
                    child: Icon(
                      Icons.sms,
                      color: RiskPalette.forRisk(risk),
                    ),
                  ),
                  title: Text(
                    sms.from,
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  subtitle: Text(
                    sms.body,
                    maxLines: 2,
                    overflow: TextOverflow.ellipsis,
                  ),
                  trailing: Text(
                    DateFormat.jm().format(sms.timestamp),
                    style: const TextStyle(color: Colors.black54),
                  ),
                  onTap: () => showDialog(
                    context: context,
                    builder: (_) => _MessageDialog(entry: e),
                  ),
                );
              },
            ),
    );
  }
}

class _MessageDialog extends StatelessWidget {
  const _MessageDialog({required this.entry});
  final EventLogEntry entry;

  @override
  Widget build(BuildContext context) {
    final sms = entry.event as SmsEvent;
    final risk = entry.riskScore ?? 0;
    return AlertDialog(
      title: Text(sms.from),
      content: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(sms.body),
          const SizedBox(height: 16),
          if (entry.tags.isNotEmpty)
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                for (final t in entry.tags)
                  Chip(
                    label: Text(t.replaceAll('_', ' '),
                        style: const TextStyle(fontSize: 12)),
                    backgroundColor: Colors.grey.shade100,
                  ),
              ],
            ),
          if (risk > 0.3)
            Padding(
              padding: const EdgeInsets.only(top: 8),
              child: Text(
                'Guardian risk: ${(risk * 100).toStringAsFixed(0)}%',
                style: TextStyle(
                  color: RiskPalette.forRisk(risk),
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
        ],
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.of(context).pop(),
          child: const Text('Close'),
        ),
      ],
    );
  }
}

class _Empty extends StatelessWidget {
  const _Empty();

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.inbox, size: 64, color: Colors.grey.shade400),
            const SizedBox(height: 16),
            Text(
              'No messages yet. Play a scenario to see Guardian in action.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey.shade700, fontSize: 16),
            ),
          ],
        ),
      ),
    );
  }
}
