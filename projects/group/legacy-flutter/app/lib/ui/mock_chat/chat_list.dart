import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/theme.dart';
import '../../data/event_log.dart';
import '../../scenarios/events.dart';

class ChatListScreen extends ConsumerWidget {
  const ChatListScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final log = ref.watch(eventLogProvider);
    final byContact = <String, List<EventLogEntry>>{};
    for (final e in log) {
      if (e.event is ChatEvent) {
        final c = (e.event as ChatEvent).contact;
        byContact.putIfAbsent(c, () => []).add(e);
      }
    }
    final contacts = byContact.keys.toList()..sort();
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        title: const Text('Chat'),
      ),
      body: contacts.isEmpty
          ? const _Empty()
          : ListView.separated(
              itemCount: contacts.length,
              separatorBuilder: (_, _) => const Divider(height: 1),
              itemBuilder: (context, i) {
                final c = contacts[i];
                final entries = byContact[c]!;
                final last = entries.last.event as ChatEvent;
                final maxRisk = entries
                    .map((e) => e.riskScore ?? 0)
                    .fold<double>(0, (a, b) => a > b ? a : b);
                return ListTile(
                  contentPadding:
                      const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
                  leading: CircleAvatar(
                    radius: 26,
                    backgroundColor:
                        RiskPalette.forRisk(maxRisk).withAlpha(30),
                    child: Text(
                      c.isNotEmpty ? c[0].toUpperCase() : '?',
                      style: TextStyle(
                        color: RiskPalette.forRisk(maxRisk),
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                  ),
                  title: Text(c,
                      style: const TextStyle(fontWeight: FontWeight.w700)),
                  subtitle: Text(
                    last.body,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  onTap: () =>
                      context.go('/chat/${Uri.encodeComponent(c)}'),
                );
              },
            ),
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
            Icon(Icons.chat_bubble_outline,
                size: 64, color: Colors.grey.shade400),
            const SizedBox(height: 16),
            Text(
              'No chats yet. Play a scenario to see an incoming thread.',
              textAlign: TextAlign.center,
              style: TextStyle(color: Colors.grey.shade700, fontSize: 16),
            ),
          ],
        ),
      ),
    );
  }
}
