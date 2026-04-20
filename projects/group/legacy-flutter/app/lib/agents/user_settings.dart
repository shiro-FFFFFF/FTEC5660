import 'package:meta/meta.dart';
import 'package:riverpod/riverpod.dart';

@immutable
class TrustedContact {
  const TrustedContact({
    required this.name,
    required this.phone,
    this.relation,
  });

  final String name;
  final String phone;
  final String? relation;

  TrustedContact copyWith({String? name, String? phone, String? relation}) {
    return TrustedContact(
      name: name ?? this.name,
      phone: phone ?? this.phone,
      relation: relation ?? this.relation,
    );
  }
}

@immutable
class UserSettings {
  const UserSettings({
    required this.accountHolder,
    this.overridePin,
    this.emergency,
    this.trusted,
  });

  final String accountHolder;

  /// 4-digit PIN required to override a Guardian block. Set by the
  /// trusted contact, NOT by the elderly user, so they can't be
  /// pressured into entering it on a scam call.
  final String? overridePin;

  final TrustedContact? emergency;
  final TrustedContact? trusted;

  UserSettings copyWith({
    String? accountHolder,
    String? overridePin,
    bool clearOverridePin = false,
    TrustedContact? emergency,
    bool clearEmergency = false,
    TrustedContact? trusted,
    bool clearTrusted = false,
  }) {
    return UserSettings(
      accountHolder: accountHolder ?? this.accountHolder,
      overridePin:
          clearOverridePin ? null : (overridePin ?? this.overridePin),
      emergency: clearEmergency ? null : (emergency ?? this.emergency),
      trusted: clearTrusted ? null : (trusted ?? this.trusted),
    );
  }
}

/// Seeded so the demo's intervention copy ("call your son David") works
/// out of the box. User can edit/overwrite from the Settings screen.
class UserSettingsNotifier extends Notifier<UserSettings> {
  @override
  UserSettings build() {
    return const UserSettings(
      accountHolder: 'Mrs. Wong',
      emergency: TrustedContact(
        name: 'David Wong',
        phone: '+852 9234 5678',
        relation: 'Son',
      ),
      trusted: TrustedContact(
        name: 'Emily Chan',
        phone: '+852 9111 2222',
        relation: 'Daughter',
      ),
    );
  }

  void setEmergency(TrustedContact c) {
    state = state.copyWith(emergency: c);
  }

  void clearEmergency() {
    state = state.copyWith(clearEmergency: true);
  }

  void setTrusted(TrustedContact c) {
    state = state.copyWith(trusted: c);
  }

  void clearTrusted() {
    state = state.copyWith(clearTrusted: true);
  }

  void setOverridePin(String pin) {
    state = state.copyWith(overridePin: pin);
  }

  void clearOverridePin() {
    state = state.copyWith(clearOverridePin: true);
  }

  void setAccountHolder(String name) {
    state = state.copyWith(accountHolder: name);
  }
}

final userSettingsProvider =
    NotifierProvider<UserSettingsNotifier, UserSettings>(
        UserSettingsNotifier.new);
