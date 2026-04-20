import 'package:meta/meta.dart';

enum EventKind { call, sms, chat, transaction }

@immutable
sealed class ScamEvent {
  const ScamEvent({
    required this.id,
    required this.timestamp,
  });

  final String id;
  final DateTime timestamp;

  EventKind get kind;
  Map<String, dynamic> toJson();
}

@immutable
class CallEvent extends ScamEvent {
  const CallEvent({
    required super.id,
    required super.timestamp,
    required this.from,
    required this.transcript,
    this.durationSeconds = 0,
    this.direction = 'incoming',
  });

  final String from;
  final String transcript;
  final int durationSeconds;
  final String direction;

  @override
  EventKind get kind => EventKind.call;

  @override
  Map<String, dynamic> toJson() => {
        'type': 'call',
        'id': id,
        'timestamp': timestamp.toIso8601String(),
        'from': from,
        'transcript': transcript,
        'duration_seconds': durationSeconds,
        'direction': direction,
      };
}

@immutable
class SmsEvent extends ScamEvent {
  const SmsEvent({
    required super.id,
    required super.timestamp,
    required this.from,
    required this.body,
  });

  final String from;
  final String body;

  @override
  EventKind get kind => EventKind.sms;

  @override
  Map<String, dynamic> toJson() => {
        'type': 'sms',
        'id': id,
        'timestamp': timestamp.toIso8601String(),
        'from': from,
        'body': body,
      };
}

@immutable
class ChatEvent extends ScamEvent {
  const ChatEvent({
    required super.id,
    required super.timestamp,
    required this.contact,
    required this.body,
    this.direction = 'incoming',
  });

  final String contact;
  final String body;
  final String direction;

  @override
  EventKind get kind => EventKind.chat;

  @override
  Map<String, dynamic> toJson() => {
        'type': 'chat',
        'id': id,
        'timestamp': timestamp.toIso8601String(),
        'contact': contact,
        'body': body,
        'direction': direction,
      };
}

@immutable
class TransactionEvent extends ScamEvent {
  const TransactionEvent({
    required super.id,
    required super.timestamp,
    required this.amountHkd,
    required this.toName,
    required this.toAccount,
    required this.newRecipient,
    this.channel = 'new_payee_transfer',
  });

  final double amountHkd;
  final String toName;
  final String toAccount;
  final bool newRecipient;
  final String channel;

  @override
  EventKind get kind => EventKind.transaction;

  @override
  Map<String, dynamic> toJson() => {
        'type': 'transaction_attempt',
        'id': id,
        'timestamp': timestamp.toIso8601String(),
        'amount_hkd': amountHkd,
        'to_name': toName,
        'to_account': toAccount,
        'new_recipient': newRecipient,
        'channel': channel,
      };
}

ScamEvent eventFromJson(Map<String, dynamic> j, DateTime ts, String id) {
  final type = j['type'] as String;
  switch (type) {
    case 'call':
      return CallEvent(
        id: id,
        timestamp: ts,
        from: j['from'] as String? ?? 'Unknown',
        transcript: j['transcript'] as String? ?? '',
        durationSeconds: (j['duration_seconds'] as num?)?.toInt() ?? 0,
        direction: j['direction'] as String? ?? 'incoming',
      );
    case 'sms':
      return SmsEvent(
        id: id,
        timestamp: ts,
        from: j['from'] as String? ?? 'Unknown',
        body: j['body'] as String? ?? '',
      );
    case 'chat':
      return ChatEvent(
        id: id,
        timestamp: ts,
        contact: j['contact'] as String? ?? 'Unknown',
        body: j['body'] as String? ?? '',
        direction: j['direction'] as String? ?? 'incoming',
      );
    case 'transaction_attempt':
      return TransactionEvent(
        id: id,
        timestamp: ts,
        amountHkd: (j['amount_hkd'] as num).toDouble(),
        toName: j['to_name'] as String? ?? 'Unknown',
        toAccount: j['to_account'] as String? ?? '',
        newRecipient: j['new_recipient'] as bool? ?? true,
        channel: j['channel'] as String? ?? 'new_payee_transfer',
      );
    default:
      throw ArgumentError('Unknown event type: $type');
  }
}
