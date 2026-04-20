import 'package:riverpod/riverpod.dart';
import 'package:meta/meta.dart';

enum ScamEntryType { number, domain, keyword }

@immutable
class ScamEntry {
  const ScamEntry({
    required this.type,
    required this.value,
    required this.weight,
    required this.tag,
    required this.note,
  });

  final ScamEntryType type;
  final String value;
  final double weight;
  final String tag;
  final String note;
}

class ScamDatabase {
  ScamDatabase(this.entries);

  final List<ScamEntry> entries;

  static ScamDatabase fromCsv(String raw) {
    final lines = raw.split('\n').where((l) => l.trim().isNotEmpty).toList();
    final out = <ScamEntry>[];
    for (var i = 1; i < lines.length; i++) {
      final parts = lines[i].split(',');
      if (parts.length < 4) continue;
      final type = switch (parts[0].trim()) {
        'number' => ScamEntryType.number,
        'domain' => ScamEntryType.domain,
        'keyword' => ScamEntryType.keyword,
        _ => null,
      };
      if (type == null) continue;
      out.add(ScamEntry(
        type: type,
        value: parts[1].trim().toLowerCase(),
        weight: double.tryParse(parts[2].trim()) ?? 0.5,
        tag: parts[3].trim(),
        note: parts.length > 4 ? parts.sublist(4).join(',').trim() : '',
      ));
    }
    return ScamDatabase(out);
  }

  Iterable<ScamEntry> badNumbers() =>
      entries.where((e) => e.type == ScamEntryType.number);
  Iterable<ScamEntry> badDomains() =>
      entries.where((e) => e.type == ScamEntryType.domain);
  Iterable<ScamEntry> keywords() =>
      entries.where((e) => e.type == ScamEntryType.keyword);
}

final scamDatabaseProvider = Provider<ScamDatabase>((ref) {
  throw UnimplementedError(
    'scamDatabaseProvider must be overridden in ProviderScope',
  );
});
