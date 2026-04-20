import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:guardian/data/scam_db.dart';
import 'package:guardian/main.dart';

void main() {
  testWidgets('GuardianApp mounts the home screen greeting',
      (WidgetTester tester) async {
    final db = ScamDatabase([]);
    await tester.pumpWidget(ProviderScope(
      overrides: [scamDatabaseProvider.overrideWithValue(db)],
      child: const GuardianApp(),
    ));
    await tester.pump(const Duration(milliseconds: 300));
    expect(find.textContaining('Guardian'), findsWidgets);
  });
}
