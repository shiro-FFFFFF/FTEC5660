import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../ui/home_screen.dart';
import '../ui/mock_bank/bank_screen.dart';
import '../ui/mock_bank/pay_bill_screen.dart';
import '../ui/mock_bank/transfer_screen.dart';
import '../ui/mock_chat/chat_list.dart';
import '../ui/mock_chat/chat_thread.dart';
import '../ui/mock_sms/sms_inbox.dart';
import '../ui/settings_screen.dart';
import '../ui/xai_screen.dart';

final GlobalKey<NavigatorState> rootNavigatorKey = GlobalKey<NavigatorState>();

final GoRouter router = GoRouter(
  navigatorKey: rootNavigatorKey,
  initialLocation: '/',
  routes: <RouteBase>[
    GoRoute(
      path: '/',
      builder: (context, state) => const HomeScreen(),
    ),
    GoRoute(
      path: '/bank',
      builder: (context, state) => const BankScreen(),
      routes: <RouteBase>[
        GoRoute(
          path: 'transfer',
          builder: (context, state) => const TransferScreen(),
        ),
        GoRoute(
          path: 'pay-bill',
          builder: (context, state) => const PayBillScreen(),
        ),
      ],
    ),
    GoRoute(
      path: '/settings',
      builder: (context, state) => const SettingsScreen(),
    ),
    GoRoute(
      path: '/sms',
      builder: (context, state) => const SmsInboxScreen(),
    ),
    GoRoute(
      path: '/chat',
      builder: (context, state) => const ChatListScreen(),
      routes: <RouteBase>[
        GoRoute(
          path: ':contact',
          builder: (context, state) => ChatThreadScreen(
            contact: Uri.decodeComponent(state.pathParameters['contact']!),
          ),
        ),
      ],
    ),
    GoRoute(
      path: '/audit',
      builder: (context, state) => const XaiScreen(),
    ),
  ],
);
