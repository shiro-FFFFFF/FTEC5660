import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../agents/bank_account.dart';
import '../../agents/context_agent.dart';
import '../../agents/intervention_agent.dart';
import '../../scenarios/events.dart';
import '../../scenarios/scenario_engine.dart';
import '../intervention/intervention_overlay.dart';

class TransferScreen extends ConsumerStatefulWidget {
  const TransferScreen({super.key});

  @override
  ConsumerState<TransferScreen> createState() => _TransferScreenState();
}

class _TransferScreenState extends ConsumerState<TransferScreen> {
  final _nameCtrl = TextEditingController();
  final _acctCtrl = TextEditingController();
  final _amtCtrl = TextEditingController();
  bool _newPayee = true;
  bool _prefilled = false;
  bool _submitting = false;

  @override
  void initState() {
    super.initState();
    // Pre-fill the form from the scenario's pending scripted transaction,
    // if any. This lets the demo operator walk the full Bank → Transfer
    // flow without typing the scripted amount / recipient by hand.
    final pending = ref.read(scenarioEngineProvider).pendingUserTransaction;
    if (pending != null) {
      _nameCtrl.text = pending.toName;
      _acctCtrl.text = pending.toAccount;
      _amtCtrl.text = pending.amountHkd.toStringAsFixed(0);
      _newPayee = pending.newRecipient;
      _prefilled = true;
    }
  }

  @override
  void dispose() {
    _nameCtrl.dispose();
    _acctCtrl.dispose();
    _amtCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    ref.listen<InterventionState>(interventionAgentProvider, (_, next) {
      final p = next.pending;
      if (p != null &&
          (p.level == InterventionLevel.fullScreen ||
              p.level == InterventionLevel.delay)) {
        showInterventionOverlay(context, ref);
      }
    });
    final account = ref.watch(bankAccountProvider);
    final fmt = NumberFormat.currency(locale: 'en_HK', symbol: 'HK\$ ');
    return Scaffold(
      backgroundColor: const Color(0xFFF4F6F9),
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/bank'),
        ),
        title: const Text('New transfer'),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              if (_prefilled) ...[
                Container(
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFF4E0),
                    border: Border.all(color: const Color(0xFFE0B878)),
                    borderRadius: BorderRadius.circular(12),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.auto_awesome,
                          color: Color(0xFF8A5A00), size: 22),
                      const SizedBox(width: 10),
                      Expanded(
                        child: Text(
                          'Pre-filled from the scripted request on the '
                          'call. Review before sending.',
                          style: TextStyle(
                              color: Colors.brown.shade800, fontSize: 14),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
              ],
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
              TextField(
                controller: _nameCtrl,
                decoration: const InputDecoration(
                  labelText: 'Recipient name',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _acctCtrl,
                decoration: const InputDecoration(
                  labelText: 'Account number',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 16),
              TextField(
                controller: _amtCtrl,
                keyboardType: TextInputType.number,
                decoration: const InputDecoration(
                  labelText: 'Amount (HKD)',
                  border: OutlineInputBorder(),
                  prefixText: 'HK\$ ',
                ),
              ),
              const SizedBox(height: 16),
              SwitchListTile(
                value: _newPayee,
                onChanged: (v) => setState(() => _newPayee = v),
                title: const Text('First-time recipient'),
                subtitle: const Text(
                    'Guardian scrutinises new payees more carefully.'),
              ),
              const SizedBox(height: 32),
              FilledButton.icon(
                onPressed: _submitting ? null : _submit,
                icon: _submitting
                    ? const SizedBox(
                        width: 18,
                        height: 18,
                        child: CircularProgressIndicator(
                            strokeWidth: 2, color: Colors.white),
                      )
                    : const Icon(Icons.send),
                label: Text(_submitting ? 'Reviewing…' : 'Review and send'),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _submit() async {
    setState(() => _submitting = true);
    final name = _nameCtrl.text.trim().isEmpty
        ? 'Unknown recipient'
        : _nameCtrl.text.trim();
    final acct = _acctCtrl.text.trim().isEmpty
        ? '000-000000-000'
        : _acctCtrl.text.trim();
    final amount = double.tryParse(_amtCtrl.text.trim()) ?? 0;
    final event = TransactionEvent(
      id: 'manual_txn_${DateTime.now().microsecondsSinceEpoch}',
      timestamp: DateTime.now(),
      amountHkd: amount,
      toName: name,
      toAccount: acct,
      newRecipient: _newPayee,
    );
    // Ingest — Guardian scores + may raise an intervention.
    await ref.read(contextAgentProvider.notifier).ingest(event);
    if (!mounted) return;
    final pending = ref.read(interventionAgentProvider).pending;
    if (pending == null) {
      // Guardian did not block — commit the transaction to the ledger.
      ref.read(bankAccountProvider.notifier).commitTransfer(event);
      ref.read(scenarioEngineProvider.notifier).resolvePendingTransaction();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(
            'Transferred HK\$ ${amount.toStringAsFixed(0)} to $name.',
          ),
        ),
      );
      context.go('/bank');
    } else {
      // Intervention is blocking — stay on this page; the overlay
      // shown by the ref.listen above will drive the next step.
      setState(() => _submitting = false);
    }
  }
}
