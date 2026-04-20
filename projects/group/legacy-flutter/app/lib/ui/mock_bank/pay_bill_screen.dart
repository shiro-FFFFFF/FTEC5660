import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../agents/bank_account.dart';

class _Bill {
  const _Bill({
    required this.name,
    required this.issuer,
    required this.amount,
    required this.dueInDays,
    required this.icon,
    required this.color,
  });
  final String name;
  final String issuer;
  final double amount;
  final int dueInDays;
  final IconData icon;
  final Color color;
}

const _bills = <_Bill>[
  _Bill(
    name: 'Electricity',
    issuer: 'CLP Power HK Ltd',
    amount: 412.00,
    dueInDays: 7,
    icon: Icons.bolt,
    color: Color(0xFFE37400),
  ),
  _Bill(
    name: 'Water',
    issuer: 'HK Water Supplies Dept',
    amount: 156.00,
    dueInDays: 12,
    icon: Icons.water_drop,
    color: Color(0xFF005A9C),
  ),
  _Bill(
    name: 'Internet',
    issuer: 'PCCW Netvigator',
    amount: 488.00,
    dueInDays: 18,
    icon: Icons.wifi,
    color: Color(0xFF1E8E3E),
  ),
  _Bill(
    name: 'Gas',
    issuer: 'Towngas',
    amount: 98.00,
    dueInDays: 21,
    icon: Icons.local_fire_department,
    color: Color(0xFFB3261E),
  ),
];

class PayBillScreen extends ConsumerWidget {
  const PayBillScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final fmt = NumberFormat.currency(locale: 'en_HK', symbol: 'HK\$ ');
    final account = ref.watch(bankAccountProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF4F6F9),
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/bank'),
        ),
        title: const Text('Pay a bill'),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Row(
                    children: [
                      const Icon(Icons.account_balance_wallet_outlined,
                          color: Color(0xFF005A9C)),
                      const SizedBox(width: 10),
                      Text(
                        'Available: ${fmt.format(account.balanceHkd)}',
                        style: const TextStyle(
                            fontSize: 16, fontWeight: FontWeight.w600),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),
              Text('Select a bill to pay',
                  style: Theme.of(context).textTheme.titleMedium),
              const SizedBox(height: 8),
              Card(
                child: Column(
                  children: [
                    for (var i = 0; i < _bills.length; i++) ...[
                      if (i > 0)
                        const Divider(height: 1, indent: 72, endIndent: 16),
                      _BillRow(
                        bill: _bills[i],
                        fmt: fmt,
                        onPay: () => _confirmPay(context, ref, _bills[i], fmt),
                      ),
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

  Future<void> _confirmPay(
    BuildContext context,
    WidgetRef ref,
    _Bill bill,
    NumberFormat fmt,
  ) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: Text('Pay ${bill.name} bill'),
        content: Text(
          'Pay ${fmt.format(bill.amount)} to ${bill.issuer}?',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(ctx).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.of(ctx).pop(true),
            child: const Text('Pay now'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    ref
        .read(bankAccountProvider.notifier)
        .payBill(name: bill.issuer, amount: bill.amount);
    if (!context.mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(
          'Paid ${fmt.format(bill.amount)} to ${bill.issuer}.',
        ),
      ),
    );
    context.go('/bank');
  }
}

class _BillRow extends StatelessWidget {
  const _BillRow(
      {required this.bill, required this.fmt, required this.onPay});
  final _Bill bill;
  final NumberFormat fmt;
  final VoidCallback onPay;

  @override
  Widget build(BuildContext context) {
    final due = bill.dueInDays <= 0
        ? 'Due today'
        : bill.dueInDays == 1
            ? 'Due tomorrow'
            : 'Due in ${bill.dueInDays} days';
    return ListTile(
      onTap: onPay,
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      leading: CircleAvatar(
        backgroundColor: bill.color.withAlpha(30),
        child: Icon(bill.icon, color: bill.color),
      ),
      title: Text(bill.name,
          style: const TextStyle(fontWeight: FontWeight.w600)),
      subtitle: Text('${bill.issuer} · $due'),
      trailing: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          Text(
            fmt.format(bill.amount),
            style: const TextStyle(
                fontSize: 16, fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 2),
          const Icon(Icons.chevron_right, color: Colors.grey, size: 20),
        ],
      ),
    );
  }
}
