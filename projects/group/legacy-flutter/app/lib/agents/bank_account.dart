import 'package:meta/meta.dart';
import 'package:riverpod/riverpod.dart';

import '../scenarios/events.dart';

enum TxnCategory { transfer, bill, salary, shopping, other }

@immutable
class BankTransaction {
  const BankTransaction({
    required this.id,
    required this.timestamp,
    required this.label,
    required this.amountHkd,
    required this.category,
    this.account,
    this.newPayee = false,
  });

  final String id;
  final DateTime timestamp;
  final String label;
  final String? account;
  final double amountHkd; // negative = debit, positive = credit
  final TxnCategory category;
  final bool newPayee;
}

@immutable
class BankAccountState {
  const BankAccountState({
    required this.balanceHkd,
    required this.history,
  });

  final double balanceHkd;
  final List<BankTransaction> history; // newest first
}

/// In-memory bank account state. The demo starts with a seeded history
/// so the Bank screen looks lived-in. Transfer/payBill calls mutate
/// balance + prepend a new history entry.
class BankAccount extends Notifier<BankAccountState> {
  static const _startingBalance = 482530.55;

  @override
  BankAccountState build() {
    final seed = DateTime.now();
    return BankAccountState(
      balanceHkd: _startingBalance,
      history: [
        BankTransaction(
          id: 'seed_pension',
          timestamp: seed.subtract(const Duration(days: 2)),
          label: 'Pension — MPF',
          amountHkd: 8500.00,
          category: TxnCategory.salary,
        ),
        BankTransaction(
          id: 'seed_groceries',
          timestamp: seed.subtract(const Duration(days: 3)),
          label: 'Groceries · Wellcome',
          amountHkd: -412.50,
          category: TxnCategory.shopping,
        ),
        BankTransaction(
          id: 'seed_son',
          timestamp: seed.subtract(const Duration(days: 5)),
          label: 'Son (David Wong)',
          amountHkd: -2000.00,
          category: TxnCategory.transfer,
        ),
        BankTransaction(
          id: 'seed_clp',
          timestamp: seed.subtract(const Duration(days: 10)),
          label: 'CLP Power HK Ltd',
          amountHkd: -412.00,
          category: TxnCategory.bill,
        ),
      ],
    );
  }

  /// Commit a confirmed transfer to the ledger. Call this only after
  /// Guardian has decided NOT to block the transaction (no blocking
  /// intervention pending). Balance is decreased; a history row is
  /// prepended so the bank screen reflects the change immediately.
  BankTransaction commitTransfer(TransactionEvent event) {
    final txn = BankTransaction(
      id: 'txn_${event.id}',
      timestamp: event.timestamp,
      label: event.toName,
      account: event.toAccount,
      amountHkd: -event.amountHkd,
      category: TxnCategory.transfer,
      newPayee: event.newRecipient,
    );
    state = BankAccountState(
      balanceHkd: state.balanceHkd - event.amountHkd,
      history: [txn, ...state.history],
    );
    return txn;
  }

  /// Pay a utility / recurring bill. No Guardian scoring (bill payments
  /// to whitelisted utilities are considered safe by default).
  BankTransaction payBill({required String name, required double amount}) {
    final txn = BankTransaction(
      id: 'bill_${DateTime.now().microsecondsSinceEpoch}',
      timestamp: DateTime.now(),
      label: name,
      amountHkd: -amount,
      category: TxnCategory.bill,
    );
    state = BankAccountState(
      balanceHkd: state.balanceHkd - amount,
      history: [txn, ...state.history],
    );
    return txn;
  }

  /// Test / demo helper: reset to the seeded state.
  void reset() {
    state = build();
  }
}

final bankAccountProvider =
    NotifierProvider<BankAccount, BankAccountState>(BankAccount.new);
