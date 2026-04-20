import 'package:meta/meta.dart';

import '../agents/context_agent.dart';
import '../data/scam_db.dart';
import '../scenarios/events.dart';

/// Contract for a tool that the Risk LLM agent can invoke during its
/// ReAct reasoning loop. Tools are stateless; any required data is
/// captured by closures in concrete implementations.
abstract class AgentTool {
  String get name;
  String get description;
  Map<String, dynamic> get parameters; // JSON Schema
  Future<Map<String, dynamic>> call(Map<String, dynamic> args);
}

/// One observed step in the agentic reasoning loop. Surfaced in the
/// audit trail so reviewers can see exactly which tools the model
/// used and what it learned.
@immutable
class ToolCallStep {
  const ToolCallStep({
    required this.tool,
    required this.args,
    required this.result,
    required this.latencyMs,
  });

  final String tool;
  final Map<String, dynamic> args;
  final Map<String, dynamic> result;
  final int latencyMs;

  Map<String, dynamic> toJson() => {
        'tool': tool,
        'args': args,
        'result': result,
        'latency_ms': latencyMs,
      };
}

class ToolRegistry {
  ToolRegistry(Iterable<AgentTool> tools)
      : _tools = {for (final t in tools) t.name: t};

  final Map<String, AgentTool> _tools;

  AgentTool? find(String name) => _tools[name];
  Iterable<AgentTool> get all => _tools.values;

  /// JSON-Schema descriptions to embed in the agent system prompt.
  List<Map<String, dynamic>> schemas() => [
        for (final t in _tools.values)
          {
            'name': t.name,
            'description': t.description,
            'parameters': t.parameters,
          },
      ];
}

// ---------------------------------------------------------------------------
// Concrete tools
// ---------------------------------------------------------------------------

class LookupNumberTool implements AgentTool {
  LookupNumberTool(this.db);
  final ScamDatabase db;

  @override
  String get name => 'lookup_number';

  @override
  String get description =>
      'Check whether a phone number (or a substring of one) is on a known '
      'scam blocklist. Returns {hit, tag, weight, note} if a match is found, '
      'else {hit: false}.';

  @override
  Map<String, dynamic> get parameters => const {
        'type': 'object',
        'properties': {
          'number': {
            'type': 'string',
            'description':
                'Phone number, prefix, or caller id, e.g. "+852 0000 0001".',
          },
        },
        'required': ['number'],
      };

  @override
  Future<Map<String, dynamic>> call(Map<String, dynamic> args) async {
    final raw = (args['number'] as String? ?? '').toLowerCase();
    for (final e in db.badNumbers()) {
      if (raw.contains(e.value)) {
        return {
          'hit': true,
          'match': e.value,
          'tag': e.tag,
          'weight': e.weight,
          'note': e.note,
        };
      }
    }
    return {'hit': false};
  }
}

class CheckDomainTool implements AgentTool {
  CheckDomainTool(this.db);
  final ScamDatabase db;

  @override
  String get name => 'check_domain';

  @override
  String get description =>
      'Scan text for URLs or domains that are known phishing / scam hosts. '
      'Returns {hit, matches: [{domain, tag, weight, note}]} or {hit: false}.';

  @override
  Map<String, dynamic> get parameters => const {
        'type': 'object',
        'properties': {
          'text': {
            'type': 'string',
            'description': 'Any free-form text that may contain URLs.',
          },
        },
        'required': ['text'],
      };

  @override
  Future<Map<String, dynamic>> call(Map<String, dynamic> args) async {
    final text = (args['text'] as String? ?? '').toLowerCase();
    final matches = <Map<String, dynamic>>[];
    for (final d in db.badDomains()) {
      if (text.contains(d.value)) {
        matches.add({
          'domain': d.value,
          'tag': d.tag,
          'weight': d.weight,
          'note': d.note,
        });
      }
    }
    return matches.isEmpty ? {'hit': false} : {'hit': true, 'matches': matches};
  }
}

class SearchKeywordsTool implements AgentTool {
  SearchKeywordsTool(this.db);
  final ScamDatabase db;

  @override
  String get name => 'search_keywords';

  @override
  String get description =>
      'Search text for phrases commonly used in scam scripts. Returns '
      '{count, total_weight, hits: [{keyword, tag, weight}]}.';

  @override
  Map<String, dynamic> get parameters => const {
        'type': 'object',
        'properties': {
          'text': {
            'type': 'string',
            'description': 'Message or transcript text to scan.',
          },
        },
        'required': ['text'],
      };

  @override
  Future<Map<String, dynamic>> call(Map<String, dynamic> args) async {
    final text = (args['text'] as String? ?? '').toLowerCase();
    final hits = <Map<String, dynamic>>[];
    double total = 0;
    for (final k in db.keywords()) {
      if (text.contains(k.value)) {
        hits.add({'keyword': k.value, 'tag': k.tag, 'weight': k.weight});
        total += k.weight;
      }
    }
    return {
      'count': hits.length,
      'total_weight': double.parse(total.toStringAsFixed(3)),
      'hits': hits,
    };
  }
}

class GetHistoryTool implements AgentTool {
  GetHistoryTool(this.snapshot);
  final ContextSnapshot snapshot;

  @override
  String get name => 'get_history';

  @override
  String get description =>
      'Summarise recent events in this session (last 72h). Useful for '
      'temporal-correlation analysis. Returns channel counts, seconds since '
      'last call/sms, and any prior max risk score.';

  @override
  Map<String, dynamic> get parameters => const {
        'type': 'object',
        'properties': {},
      };

  @override
  Future<Map<String, dynamic>> call(Map<String, dynamic> args) async {
    var calls = 0, sms = 0, chats = 0, txns = 0;
    for (final e in snapshot.recentEvents) {
      switch (e) {
        case CallEvent():
          calls++;
        case SmsEvent():
          sms++;
        case ChatEvent():
          chats++;
        case TransactionEvent():
          txns++;
      }
    }
    return {
      'recent_event_count': snapshot.recentEventCount,
      'channels': {'call': calls, 'sms': sms, 'chat': chats, 'transaction': txns},
      'has_recent_call': snapshot.hasRecentCall,
      'has_recent_sms': snapshot.hasRecentSms,
      'seconds_since_last_call':
          snapshot.hasRecentCall ? snapshot.secondsSinceLastCall : null,
      'seconds_since_last_sms':
          snapshot.hasRecentSms ? snapshot.secondsSinceLastSms : null,
      'prior_max_risk':
          double.parse(snapshot.priorMaxRisk.toStringAsFixed(3)),
    };
  }
}

/// Convenience: build the standard 4-tool registry for a given snapshot.
ToolRegistry buildDefaultToolRegistry({
  required ScamDatabase db,
  required ContextSnapshot snapshot,
}) {
  return ToolRegistry([
    LookupNumberTool(db),
    CheckDomainTool(db),
    SearchKeywordsTool(db),
    GetHistoryTool(snapshot),
  ]);
}
