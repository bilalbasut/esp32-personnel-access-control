#pragma once
#include <Arduino.h>

class IOController {
public:
    static void init();
    static void grantAccess();
    static void denyAccess();
    static void update();
    static void handleExitButton();
    static bool isRelayRunning();
};