#pragma once
#include <Arduino.h>

class NetworkManager {
public:
    static void taskLoop(void* parameter);
    static bool isMqttConnected();
};