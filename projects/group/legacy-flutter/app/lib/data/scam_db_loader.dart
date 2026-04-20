import 'package:flutter/services.dart';

import 'scam_db.dart';

Future<ScamDatabase> loadScamDatabaseFromAssets() async {
  final raw = await rootBundle.loadString('assets/scam_db.csv');
  return ScamDatabase.fromCsv(raw);
}
