import 'package:flutter/material.dart';

const Color _primary = Color(0xFF005A9C);
const Color _danger = Color(0xFFB3261E);
const Color _warning = Color(0xFFE37400);
const Color _surface = Color(0xFFFDFDFD);

ThemeData get guardianTheme {
  final base = ThemeData(
    useMaterial3: true,
    colorScheme: ColorScheme.fromSeed(
      seedColor: _primary,
      primary: _primary,
      error: _danger,
      surface: _surface,
      brightness: Brightness.light,
    ),
    visualDensity: VisualDensity.comfortable,
  );
  return base.copyWith(
    textTheme: base.textTheme.copyWith(
      displayLarge:
          base.textTheme.displayLarge?.copyWith(fontWeight: FontWeight.w700),
      headlineMedium: base.textTheme.headlineMedium
          ?.copyWith(fontWeight: FontWeight.w700),
      titleLarge:
          base.textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w700),
      bodyLarge: base.textTheme.bodyLarge?.copyWith(fontSize: 19),
      bodyMedium: base.textTheme.bodyMedium?.copyWith(fontSize: 17),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(64, 60),
        textStyle: const TextStyle(
          fontSize: 20,
          fontWeight: FontWeight.w600,
        ),
        padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 16),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(64, 56),
        textStyle: const TextStyle(fontSize: 18),
      ),
    ),
    cardTheme: CardThemeData(
      elevation: 0,
      margin: EdgeInsets.zero,
      color: Colors.white,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(16),
        side: const BorderSide(color: Color(0xFFE4E7EB)),
      ),
    ),
    appBarTheme: const AppBarTheme(
      backgroundColor: Colors.white,
      foregroundColor: Color(0xFF15181C),
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        fontSize: 22,
        fontWeight: FontWeight.w700,
        color: Color(0xFF15181C),
      ),
    ),
  );
}

class RiskPalette {
  static const Color safe = Color(0xFF1E8E3E);
  static const Color watch = Color(0xFFE37400);
  static const Color alert = Color(0xFFB3261E);
  static const Color critical = Color(0xFF8C1D18);

  static Color forRisk(double risk) {
    if (risk >= 0.85) return critical;
    if (risk >= 0.6) return alert;
    if (risk >= 0.3) return watch;
    return safe;
  }

  static String labelFor(double risk) {
    if (risk >= 0.85) return 'CRITICAL';
    if (risk >= 0.6) return 'HIGH';
    if (risk >= 0.3) return 'ELEVATED';
    return 'NORMAL';
  }
}

const Color dangerColor = _danger;
const Color warningColor = _warning;
