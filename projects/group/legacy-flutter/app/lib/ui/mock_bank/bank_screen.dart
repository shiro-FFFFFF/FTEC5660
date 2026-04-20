import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../agents/bank_account.dart';
import '../../agents/intervention_agent.dart';
import '../intervention/intervention_overlay.dart';
import '../status_bar.dart';

class BankScreen extends ConsumerWidget {
  const BankScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    ref.listen<InterventionState>(interventionAgentProvider, (_, next) {
      final p = next.pending;
      if (p != null &&
          (p.level == InterventionLevel.fullScreen ||
              p.level == InterventionLevel.delay)) {
        showInterventionOverlay(context, ref);
      }
    });
    final fmt = NumberFormat.currency(locale: 'en_HK', symbol: 'HK\$ ');
    final account = ref.watch(bankAccountProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF4F6F9),
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        title: const Text('HSBC Hong Kong'),
        actions: [
          IconButton(
            tooltip: 'Settings',
            icon: const Icon(Icons.settings_outlined),
            onPressed: () => context.go('/settings'),
          ),
        ],
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 720),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              const GuardianStatusBar(showSettings: false),
              const SizedBox(height: 12),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('Savings · 012-345678-000',
                          style: Theme.of(context).textTheme.bodyMedium),
                      const SizedBox(height: 8),
                      Text(
                        fmt.format(account.balanceHkd),
                        style: Theme.of(context)
                            .textTheme
                            .displaySmall
                            ?.copyWith(fontWeight: FontWeight.w800),
                      ),
                      const SizedBox(height: 4),
                      const Text('Available balance',
                          style: TextStyle(color: Colors.black54)),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: FilledButton.icon(
                      onPressed: () => context.go('/bank/transfer'),
                      icon: const Icon(Icons.arrow_outward),
                      label: const Text('Transfer'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: OutlinedButton.icon(
                      onPressed: () => context.go('/bank/pay-bill'),
                      icon: const Icon(Icons.receipt_long),
                      label: const Text('Pay bill'),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 24),
              Text('Recent transactions',
                  style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: 8),
              Card(
                child: Column(
                  children: [
                    for (var i = 0; i < account.history.length; i++) ...[
                      if (i > 0)
                        const Divider(height: 1, indent: 72, endIndent: 16),
                      _TxnRow(txn: account.history[i], fmt: fmt),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TxnRow extends StatelessWidget {
  const _TxnRow({required this.txn, required this.fmt});
  final BankTransaction txn;
  final NumberFormat fmt;

  @override
  Widget build(BuildContext context) {
    final debit = txn.amountHkd < 0;
    final amountColor = debit ? Colors.black87 : const Color(0xFF1E8E3E);
    final iconData = switch (txn.category) {
      TxnCategory.transfer => debit ? Icons.north_east : Icons.south_west,
      TxnCategory.bill => Icons.receipt_long,
      TxnCategory.salary => Icons.south_west,
      TxnCategory.shopping => Icons.shopping_bag_outlined,
      TxnCategory.other => Icons.swap_horiz,
    };
    final when = _relativeDate(txn.timestamp);
    return ListTile(
      leading: CircleAvatar(
        backgroundColor: Colors.grey.shade200,
        child: Icon(iconData, color: amountColor),
      ),
      title: Text(
        txn.label,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      subtitle: Text(
        txn.account == null ? when : '${txn.account} · $when',
        style: TextStyle(color: Colors.grey.shade600, fontSize: 13),
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
      ),
      trailing: Text(
        fmt.format(txn.amountHkd),
        style: TextStyle(color: amountColor, fontWeight: FontWeight.w600),
      ),
    );
  }

  String _relativeDate(DateTime ts) {
    final now = DateTime.now();
    final diff = now.difference(ts);
    if (diff.inMinutes < 1) return 'just now';
    if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
    if (diff.inHours < 24) return '${diff.inHours} h ago';
    if (diff.inDays == 1) return 'yesterday';
    if (diff.inDays < 7) return '${diff.inDays} days ago';
    return DateFormat('d MMM').format(ts);
  }
}
