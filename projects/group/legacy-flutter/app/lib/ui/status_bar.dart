import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../llm/llm_runtime.dart';

class GuardianStatusBar extends ConsumerWidget {
  const GuardianStatusBar({super.key, this.showSettings = true});

  /// When true (default), a gear icon is shown at the far right that
  /// navigates to the global Settings screen. Set to false on screens
  /// that already provide their own settings entry point (e.g. the
  /// Bank app bar).
  final bool showSettings;

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(llmStatusProvider);
    final label = status.when(
      data: (name) => name,
      loading: () => 'detecting…',
      error: (_, _) => 'heuristic',
    );
    final now = DateFormat.jm().format(DateTime.now());
    return Container(
      padding: const EdgeInsets.fromLTRB(20, 12, 8, 8),
      color: Colors.white,
      child: Row(
        children: [
          Text(now,
              style:
                  const TextStyle(fontSize: 16, fontWeight: FontWeight.w600)),
          const Spacer(),
          Container(
            padding:
                const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
            decoration: BoxDecoration(
              color: const Color(0xFF005A9C).withAlpha(20),
              borderRadius: BorderRadius.circular(20),
            ),
            child: Row(
              children: [
                const Icon(Icons.shield_outlined,
                    size: 16, color: Color(0xFF005A9C)),
                const SizedBox(width: 6),
                Text(
                  'Guardian • $label',
                  style: const TextStyle(
                    color: Color(0xFF005A9C),
                    fontWeight: FontWeight.w600,
                    fontSize: 13,
                  ),
                ),
              ],
            ),
          ),
          if (showSettings) ...[
            const SizedBox(width: 4),
            IconButton(
              tooltip: 'Settings',
              icon: const Icon(Icons.settings_outlined),
              color: Colors.black54,
              onPressed: () => context.go('/settings'),
            ),
          ] else
            const SizedBox(width: 12),
        ],
      ),
    );
  }
}
