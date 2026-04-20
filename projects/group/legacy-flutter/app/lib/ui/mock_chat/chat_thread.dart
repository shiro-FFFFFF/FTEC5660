import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../core/theme.dart';
import '../../data/event_log.dart';
import '../../scenarios/events.dart';

class ChatThreadScreen extends ConsumerWidget {
  const ChatThreadScreen({required this.contact, super.key});
  final String contact;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final entries = ref
        .watch(eventLogProvider)
        .where((e) =>
            e.event is ChatEvent &&
            (e.event as ChatEvent).contact == contact)
        .toList();
    final maxRisk = entries
        .map((e) => e.riskScore ?? 0)
        .fold<double>(0, (a, b) => a > b ? a : b);
    return Scaffold(
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/chat'),
        ),
        title: Text(contact),
        actions: [
          if (maxRisk >= 0.3)
            Padding(
              padding: const EdgeInsets.only(right: 12),
              child: Chip(
                label: Text('${(maxRisk * 100).toStringAsFixed(0)}%'),
                backgroundColor: RiskPalette.forRisk(maxRisk).withAlpha(40),
                labelStyle: TextStyle(
                  color: RiskPalette.forRisk(maxRisk),
                  fontWeight: FontWeight.w700,
                ),
              ),
            ),
        ],
      ),
      body: ListView.builder(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        itemCount: entries.length,
        itemBuilder: (context, i) {
          final e = entries[i];
          final chat = e.event as ChatEvent;
          final isIncoming = chat.direction == 'incoming';
          final risk = e.riskScore ?? 0;
          final bubbleColor = isIncoming
              ? Colors.white
              : const Color(0xFF005A9C).withAlpha(20);
          return Align(
            alignment:
                isIncoming ? Alignment.centerLeft : Alignment.centerRight,
            child: Container(
              margin: const EdgeInsets.symmetric(vertical: 6),
              padding:
                  const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              constraints: BoxConstraints(
                maxWidth: MediaQuery.of(context).size.width * 0.8,
              ),
              decoration: BoxDecoration(
                color: bubbleColor,
                borderRadius: BorderRadius.circular(14),
                border: Border.all(
                  color: risk >= 0.3
                      ? RiskPalette.forRisk(risk).withAlpha(80)
                      : Colors.grey.shade300,
                ),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(chat.body, style: const TextStyle(fontSize: 16)),
                  const SizedBox(height: 4),
                  Text(
                    DateFormat.jm().format(chat.timestamp),
                    style: const TextStyle(fontSize: 11, color: Colors.black45),
                  ),
                ],
              ),
            ),
          );
        },
      ),
    );
  }
}
