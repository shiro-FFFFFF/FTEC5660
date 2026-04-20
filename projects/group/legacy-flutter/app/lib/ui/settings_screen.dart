import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../agents/user_settings.dart';

class SettingsScreen extends ConsumerWidget {
  const SettingsScreen({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final settings = ref.watch(userSettingsProvider);
    return Scaffold(
      backgroundColor: const Color(0xFFF4F6F9),
      appBar: AppBar(
        leading: IconButton(
          icon: const Icon(Icons.arrow_back),
          onPressed: () => context.go('/'),
        ),
        title: const Text('Settings'),
      ),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 560),
          child: ListView(
            padding: const EdgeInsets.all(20),
            children: [
              _SectionHeader('Account holder'),
              Card(
                child: ListTile(
                  leading: const CircleAvatar(
                    backgroundColor: Color(0xFFE3EDF5),
                    child: Icon(Icons.person, color: Color(0xFF005A9C)),
                  ),
                  title: Text(
                    settings.accountHolder,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  subtitle: const Text('Tap to change'),
                  trailing: const Icon(Icons.chevron_right),
                  onTap: () => _editAccountHolder(context, ref),
                ),
              ),
              const SizedBox(height: 16),
              _SectionHeader('Who should we contact in an emergency?'),
              _ContactCard(
                label: 'Emergency contact',
                sublabel:
                    'We will suggest calling this person if Guardian spots a scam.',
                contact: settings.emergency,
                onEdit: () => _editContact(
                  context,
                  ref,
                  title: 'Emergency contact',
                  initial: settings.emergency,
                  onSave: (c) =>
                      ref.read(userSettingsProvider.notifier).setEmergency(c),
                  onClear: () =>
                      ref.read(userSettingsProvider.notifier).clearEmergency(),
                ),
              ),
              const SizedBox(height: 12),
              _ContactCard(
                label: 'Trusted helper',
                sublabel:
                    'Can help you set the override PIN and review unusual '
                    'transactions.',
                contact: settings.trusted,
                onEdit: () => _editContact(
                  context,
                  ref,
                  title: 'Trusted helper',
                  initial: settings.trusted,
                  onSave: (c) =>
                      ref.read(userSettingsProvider.notifier).setTrusted(c),
                  onClear: () =>
                      ref.read(userSettingsProvider.notifier).clearTrusted(),
                ),
              ),
              const SizedBox(height: 16),
              _SectionHeader('Override PIN (optional)'),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(Icons.lock_outline,
                              color: Color(0xFF005A9C)),
                          const SizedBox(width: 10),
                          Text(
                            settings.overridePin == null
                                ? 'No override PIN set'
                                : 'Override PIN is set',
                            style: const TextStyle(
                                fontSize: 16, fontWeight: FontWeight.w600),
                          ),
                        ],
                      ),
                      const SizedBox(height: 8),
                      Text(
                        'Ask your trusted helper to set a 4-digit PIN. '
                        'Guardian will only ask for it if you want to '
                        'override a scam warning. Day-to-day transfers '
                        'do NOT require this PIN.',
                        style: TextStyle(
                            color: Colors.grey.shade700, fontSize: 14),
                      ),
                      const SizedBox(height: 12),
                      Row(
                        children: [
                          FilledButton.tonalIcon(
                            onPressed: () => _setPin(context, ref),
                            icon: const Icon(Icons.edit),
                            label: Text(settings.overridePin == null
                                ? 'Set PIN'
                                : 'Change PIN'),
                          ),
                          const SizedBox(width: 12),
                          if (settings.overridePin != null)
                            OutlinedButton.icon(
                              onPressed: () => ref
                                  .read(userSettingsProvider.notifier)
                                  .clearOverridePin(),
                              icon: const Icon(Icons.delete_outline),
                              label: const Text('Remove'),
                            ),
                        ],
                      ),
                    ],
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _editAccountHolder(
      BuildContext context, WidgetRef ref) async {
    final current = ref.read(userSettingsProvider).accountHolder;
    final ctrl = TextEditingController(text: current);
    final name = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Account holder name'),
        content: TextField(
          controller: ctrl,
          autofocus: true,
          decoration: const InputDecoration(border: OutlineInputBorder()),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(ctx, ctrl.text.trim()),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (name != null && name.isNotEmpty) {
      ref.read(userSettingsProvider.notifier).setAccountHolder(name);
    }
  }

  Future<void> _editContact(
    BuildContext context,
    WidgetRef ref, {
    required String title,
    required TrustedContact? initial,
    required void Function(TrustedContact) onSave,
    required VoidCallback onClear,
  }) async {
    final result = await showDialog<_ContactEditResult>(
      context: context,
      builder: (ctx) => _ContactEditDialog(title: title, initial: initial),
    );
    if (result == null) return;
    if (result.clear) {
      onClear();
    } else if (result.contact != null) {
      onSave(result.contact!);
    }
  }

  Future<void> _setPin(BuildContext context, WidgetRef ref) async {
    final ctrl = TextEditingController();
    final confirmCtrl = TextEditingController();
    final pin = await showDialog<String>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Set override PIN'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'Choose a 4-digit PIN. The trusted helper should do this.',
              style: TextStyle(fontSize: 14),
            ),
            const SizedBox(height: 16),
            TextField(
              controller: ctrl,
              autofocus: true,
              keyboardType: TextInputType.number,
              obscureText: true,
              maxLength: 4,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: const InputDecoration(
                labelText: 'New PIN',
                border: OutlineInputBorder(),
                counterText: '',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: confirmCtrl,
              keyboardType: TextInputType.number,
              obscureText: true,
              maxLength: 4,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              decoration: const InputDecoration(
                labelText: 'Confirm PIN',
                border: OutlineInputBorder(),
                counterText: '',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              if (ctrl.text.length == 4 && ctrl.text == confirmCtrl.text) {
                Navigator.pop(ctx, ctrl.text);
              } else {
                ScaffoldMessenger.of(ctx).showSnackBar(
                  const SnackBar(
                    content: Text(
                        'Please enter 4 digits matching in both fields.'),
                  ),
                );
              }
            },
            child: const Text('Save'),
          ),
        ],
      ),
    );
    if (pin != null && pin.length == 4) {
      ref.read(userSettingsProvider.notifier).setOverridePin(pin);
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Override PIN saved.')),
      );
    }
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader(this.text);
  final String text;
  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(4, 4, 4, 8),
      child: Text(
        text,
        style: TextStyle(
          fontSize: 13,
          fontWeight: FontWeight.w700,
          color: Colors.grey.shade700,
          letterSpacing: 0.4,
        ),
      ),
    );
  }
}

class _ContactCard extends StatelessWidget {
  const _ContactCard({
    required this.label,
    required this.sublabel,
    required this.contact,
    required this.onEdit,
  });
  final String label;
  final String sublabel;
  final TrustedContact? contact;
  final VoidCallback onEdit;

  @override
  Widget build(BuildContext context) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label,
                style: const TextStyle(
                    fontSize: 16, fontWeight: FontWeight.w700)),
            const SizedBox(height: 4),
            Text(sublabel,
                style:
                    TextStyle(color: Colors.grey.shade700, fontSize: 13)),
            const SizedBox(height: 12),
            if (contact == null)
              Row(
                children: [
                  const Icon(Icons.person_off_outlined,
                      color: Colors.black45, size: 20),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      'Not set',
                      style:
                          TextStyle(color: Colors.grey.shade600, fontSize: 15),
                    ),
                  ),
                  FilledButton.tonal(
                    onPressed: onEdit,
                    child: const Text('Add'),
                  ),
                ],
              )
            else
              Row(
                children: [
                  CircleAvatar(
                    backgroundColor: const Color(0xFFE3EDF5),
                    child: Text(
                      _initials(contact!.name),
                      style: const TextStyle(
                          color: Color(0xFF005A9C),
                          fontWeight: FontWeight.w700),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${contact!.name}'
                          '${contact!.relation != null ? " · ${contact!.relation}" : ""}',
                          style: const TextStyle(
                              fontWeight: FontWeight.w600, fontSize: 15),
                        ),
                        const SizedBox(height: 2),
                        Text(contact!.phone,
                            style: TextStyle(
                                color: Colors.grey.shade700, fontSize: 14)),
                      ],
                    ),
                  ),
                  IconButton(
                    onPressed: onEdit,
                    icon: const Icon(Icons.edit_outlined),
                    tooltip: 'Edit',
                  ),
                ],
              ),
          ],
        ),
      ),
    );
  }

  String _initials(String name) {
    final parts = name.trim().split(RegExp(r'\s+'));
    if (parts.isEmpty) return '?';
    if (parts.length == 1) return parts.first.substring(0, 1).toUpperCase();
    return (parts.first[0] + parts.last[0]).toUpperCase();
  }
}

class _ContactEditResult {
  _ContactEditResult({this.contact, this.clear = false});
  final TrustedContact? contact;
  final bool clear;
}

class _ContactEditDialog extends StatefulWidget {
  const _ContactEditDialog({required this.title, this.initial});
  final String title;
  final TrustedContact? initial;

  @override
  State<_ContactEditDialog> createState() => _ContactEditDialogState();
}

class _ContactEditDialogState extends State<_ContactEditDialog> {
  late final TextEditingController _name =
      TextEditingController(text: widget.initial?.name ?? '');
  late final TextEditingController _phone =
      TextEditingController(text: widget.initial?.phone ?? '');
  late final TextEditingController _relation =
      TextEditingController(text: widget.initial?.relation ?? '');

  @override
  void dispose() {
    _name.dispose();
    _phone.dispose();
    _relation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AlertDialog(
      title: Text(widget.title),
      content: SizedBox(
        width: 380,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            TextField(
              controller: _name,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Full name',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _phone,
              keyboardType: TextInputType.phone,
              decoration: const InputDecoration(
                labelText: 'Phone number',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: _relation,
              decoration: const InputDecoration(
                labelText: 'Relation (e.g. Son, Daughter)',
                border: OutlineInputBorder(),
              ),
            ),
          ],
        ),
      ),
      actions: [
        if (widget.initial != null)
          TextButton(
            onPressed: () => Navigator.pop(
                context, _ContactEditResult(clear: true)),
            style: TextButton.styleFrom(foregroundColor: Colors.red),
            child: const Text('Remove'),
          ),
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
        FilledButton(
          onPressed: () {
            final name = _name.text.trim();
            final phone = _phone.text.trim();
            if (name.isEmpty || phone.isEmpty) {
              ScaffoldMessenger.of(context).showSnackBar(
                const SnackBar(
                  content: Text('Name and phone are required.'),
                ),
              );
              return;
            }
            Navigator.pop(
              context,
              _ContactEditResult(
                contact: TrustedContact(
                  name: name,
                  phone: phone,
                  relation: _relation.text.trim().isEmpty
                      ? null
                      : _relation.text.trim(),
                ),
              ),
            );
          },
          child: const Text('Save'),
        ),
      ],
    );
  }
}
