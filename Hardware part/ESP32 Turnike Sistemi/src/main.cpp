#include <Arduino.h>
#include <Wire.h>
#include "RTClib.h"
#include "FS.h"
#include <LittleFS.h>
#include <SPI.h>
#include <Ethernet.h>
#include <ArduinoHttpClient.h>

// --- 1. Hardware Pins ---
// Outputs
#define RELAY_PIN       32
#define BUZZER_PIN      33
#define GREEN_LED_PIN   25
#define RED_LED_PIN     17

// Inputs (Restored)
#define EXIT_BUTTON_PIN 35
#define DOOR_SENSOR_PIN 34

// UART Scanner
#define SCANNER_RX_PIN  27
#define SCANNER_TX_PIN  26

// --- W5500 Pins ---
#define W5500_CS_PIN  5
#define W5500_RST_PIN 4

// --- 2. RTC Object ---
RTC_DS3231 rtc;

// --- 3. Non-Blocking Timer Variables ---
// Relay & Success Beep Timers
unsigned long relayStartTime = 0;
bool isRelayActive = false;

unsigned long successBeepStartTime = 0;
bool isSuccessBeepActive = false;

// Deny Sequence Timers
bool isDenySequenceActive = false;
unsigned long lastDenyStepTime = 0;
int denyBeepCount = 0;
bool denyLedState = false;
bool hasDoorOpened = false;
// --- 4. Hardware Control Functions ---
void grantAccess() {
  // Cancel any active deny sequence to prevent LED conflicts
  isDenySequenceActive = false; 
  digitalWrite(RED_LED_PIN, LOW);
  hasDoorOpened = false;

  // Start the 3-second relay timer
  isRelayActive = true;
  relayStartTime = millis();
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(RELAY_PIN, HIGH); 
  
  // Start the 250ms buzzer timer
  isSuccessBeepActive = true;
  successBeepStartTime = millis();
  digitalWrite(BUZZER_PIN, HIGH);
}

void denyAccess() {
  // If the door is already unlocked, ignore the deny beep so it doesn't lock people out
  if (isRelayActive) return; 

  // Start the deny sequence state machine
  isDenySequenceActive = true;
  denyBeepCount = 0;
  denyLedState = true; // Start with LEDs ON
  lastDenyStepTime = millis();
  
  digitalWrite(RED_LED_PIN, HIGH);
  digitalWrite(BUZZER_PIN, HIGH);
}

bool isCardAuthorized(String scannedUID) {
  scannedUID.trim(); 
  
  // Open the file in READ mode
  File file = LittleFS.open("/database.txt", FILE_READ);
  if (!file) {
    Serial.println("Error: Could not read database file.");
    return false; 
  }

  // Loop through every line in the text file
  while (file.available()) {
    String line = file.readStringUntil('\n');
    line.trim(); // Strip hidden carriage returns from the text file
    
    if (line == scannedUID) {
      file.close(); // Always close the file to free up memory
      return true;
    }
  }
  
  file.close(); 
  return false;
}

  void logAccess(String timestamp, String scannedUID, bool isGranted) {
  // Open the file in APPEND mode to safely add to the bottom of the list
  File logFile = LittleFS.open("/logs.txt", FILE_APPEND);
  
  if (!logFile) {
    Serial.println("Error: Could not open /logs.txt for appending.");
    return;
  }

  // Convert the boolean into a readable string
  String accessStatus = isGranted ? "GRANTED" : "DENIED";
  
  // Create a clean CSV format: Timestamp, UID, Status, SyncFlag
  // Example: 2026/08/12 16:10:00,A1B2C3D4,GRANTED,0
  String logEntry = timestamp + "," + scannedUID + "," + accessStatus + ",0";
  
  // Write it to the flash drive and close the file
  logFile.println(logEntry);
  logFile.close();
  
  Serial.println("Saved to offline queue -> " + logEntry);
}

// Define a MAC address for the ESP32  ---> MUST CHANGE THESE BEFORE DEPLOYMENT <---
byte mac[] = { 0xDE, 0xAD, 0xBE, 0xEF, 0xFE, 0xED };

char serverAddress[] = "192.168.1.100";  // Your server IP address
int port = 8080;                         // Server port
String apiPath = "/api/access-logs";     // API endpoint

EthernetClient ethClient;
HttpClient http = HttpClient(ethClient, serverAddress, port);

// --- RAM Tracker for Flash Wear Prevention ---
size_t lastSyncedPosition = 0;

// Define a FreeRTOS Task Handle
TaskHandle_t NetworkTask;

// --- The Core 0 Network Function ---
// Everything inside this function runs entirely on Core 0 in the background.
void networkTaskCode(void * pvParameters) {
  Serial.print("Network Task running on Core: ");
  Serial.println(xPortGetCoreID());

  pinMode(W5500_RST_PIN, OUTPUT);
  digitalWrite(W5500_RST_PIN, LOW);
  delay(100);
  digitalWrite(W5500_RST_PIN, HIGH);
  delay(500);
  
  Ethernet.init(W5500_CS_PIN);
  
  if (Ethernet.begin(mac) == 0) {
    Serial.println("Failed to configure Ethernet using DHCP");
  } else {
    Serial.print("Ethernet connected! IP Address: ");
    Serial.println(Ethernet.localIP());
  }

  for(;;) {
    Ethernet.maintain(); 
    
    if (Ethernet.linkStatus() == LinkON) {
      
      File logFile = LittleFS.open("/logs.txt", FILE_READ);
      
      if (logFile && logFile.size() > 0) {
        
        // 1. Jump to the last successfully sent byte (Saves Flash reads)
        logFile.seek(lastSyncedPosition);
        bool networkFailed = false;

        while (logFile.available()) {
          String logLine = logFile.readStringUntil('\n');
          logLine.trim();
          
          if (logLine.length() > 0) {
            
            // Send to server
            String postData = "{\"log\":\"" + logLine + "\"}";
            
            http.beginRequest();
            http.post(apiPath);
            http.sendHeader("Content-Type", "application/json");
            http.sendHeader("Content-Length", postData.length());
            http.beginBody();
            http.print(postData);
            http.endRequest();

            int statusCode = http.responseStatusCode();
            
            if (statusCode == 200 || statusCode == 201) {
              Serial.println("SYNC SUCCESS: " + logLine);
              // 2. Update the RAM bookmark to the current position
              lastSyncedPosition = logFile.position();
            } else {
              Serial.println("SYNC FAILED. Stopping queue.");
              networkFailed = true;
              break; // Break the while loop; stop trying to send logs until next cycle
            }
          }
        }
        
        // 3. The Only Flash Write Operation
        // If we reached the end of the file and the network never failed
        if (!networkFailed && lastSyncedPosition == logFile.size()) {
          logFile.close(); 
          LittleFS.remove("/logs.txt"); // Delete the file ONE time
          lastSyncedPosition = 0;       // Reset the RAM bookmark
          Serial.println("All logs synced. Flash file wiped cleanly.");
        } else {
          logFile.close(); 
        }
      }
    }

    // Task sleeps for 5 seconds
    vTaskDelay(5000 / portTICK_PERIOD_MS); 
  }
}

void handleHardwareTimers() {
  unsigned long currentMillis = millis();

  // 1. Check Relay Timer (3000ms / 3 seconds)
  if (isRelayActive && (currentMillis - relayStartTime >= 3000)) {
    isRelayActive = false;
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(RELAY_PIN, LOW);
  }

  // 2. Check Success Beep Timer (250ms)
  if (isSuccessBeepActive && (currentMillis - successBeepStartTime >= 250)) {
    isSuccessBeepActive = false;
    digitalWrite(BUZZER_PIN, LOW);
  }

  // 3. Check Deny Sequence Timer (Rapid 150ms toggles)
  if (isDenySequenceActive) {
    if (currentMillis - lastDenyStepTime >= 150) {
      lastDenyStepTime = currentMillis; // Reset the stopwatch for the next toggle
      
      if (denyLedState) {
        // Hardware was ON, turn it OFF
        digitalWrite(RED_LED_PIN, LOW);
        digitalWrite(BUZZER_PIN, LOW);
        denyLedState = false;
        denyBeepCount++; // Count one full beep
      } else {
        // Hardware was OFF, check if we need another beep
        if (denyBeepCount < 3) {
          digitalWrite(RED_LED_PIN, HIGH);
          digitalWrite(BUZZER_PIN, HIGH);
          denyLedState = true;
        } else {
          // 3 beeps completed, end the sequence
          isDenySequenceActive = false;
        }
      }
    }
  }
}
// --- 6. File System Initialization ---
void initFileSystem() {
  // The 'true' parameter enables auto-formatting on the very first boot
  if (!LittleFS.begin(true)) {
    Serial.println("CRITICAL ERROR: Failed to mount LittleFS!");
    return;
  }
  Serial.println("LittleFS mounted successfully.");

  // Check if our database file exists
  if (!LittleFS.exists("/database.txt")) {
    Serial.println("No database found. Creating default /database.txt...");
    
    // Open the file in WRITE mode
    File file = LittleFS.open("/database.txt", FILE_WRITE);
    if (!file) {
      Serial.println("Error: Could not create database file.");
      return;
    }
    
    // Write your starter UIDs to the file ---> MUST CHANGE THESE BEFORE DEPLOYMENT <---
    file.println("A1B2C3D4");
    file.println("98765432");
    file.close();
    
    Serial.println("Default database created.");
  } else {
    Serial.println("Existing /database.txt loaded.");
  }
}


// --- 4. System Setup ---
void setup() {
  Serial.begin(115200);
  delay(1000);
  
  // Initialize the File System first
  initFileSystem();

  // Initialize Scanner on Serial1
  Serial1.begin(9600, SERIAL_8N1, SCANNER_RX_PIN, SCANNER_TX_PIN);

  // Initialize Outputs
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);

  // Initialize Inputs (Restored)
  pinMode(EXIT_BUTTON_PIN, INPUT);
  pinMode(DOOR_SENSOR_PIN, INPUT);

  // Initialize RTC
  if (!rtc.begin()) {
    Serial.println("CRITICAL ERROR: Couldn't find RTC! Check wiring.");
    while (1); 
  }

  if (rtc.lostPower()) {
    Serial.println("RTC lost power! Resetting time...");
    rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
  }

  Serial.println("System Ready. Waiting for card scan...");

  // Launch the Network Task on Core 0
  // Parameters: Function Name, Task Name, Stack Size, Task Input, Priority, Handle, Core ID
  xTaskCreatePinnedToCore(
    networkTaskCode,   
    "NetworkTask",     
    10000,            
    NULL,              
    1,                 
    &NetworkTask,      
    0                  
  );
  
  // By default, your standard setup() and loop() are already running on Core 1.
  Serial.print("Main hardware loop running on Core: ");
  Serial.println(xPortGetCoreID());
}

// --- 5. Main Loop ---

void loop() {

  handleHardwareTimers(); 

  // --- 1. Exit Button Logic ---
  // If the button is pressed (LOW) and the door isn't already unlocked
  if (digitalRead(EXIT_BUTTON_PIN) == LOW && !isRelayActive) {
    Serial.println("Exit Button Pressed -> GRANTED");
    grantAccess();
  }

  // --- 2. Smart Auto-Relock (Anti-Tailgating) Logic ---
  if (isRelayActive) {
    bool currentDoorState = digitalRead(DOOR_SENSOR_PIN);
    
    // Detect if the door has been pushed open
    if (currentDoorState == HIGH) {
      hasDoorOpened = true; 
    }
    
    // If the door was opened, and is now closed again, kill the 3-second timer early
    if (hasDoorOpened && currentDoorState == LOW) {
      isRelayActive = false;
      digitalWrite(GREEN_LED_PIN, LOW);
      digitalWrite(RELAY_PIN, LOW);
      Serial.println("Door securely closed. Timer overridden, relocked early.");
      
      // Reset so it doesn't trigger repeatedly
      hasDoorOpened = false; 
    }
  }

  // --- 3. UART Scanner Logic ---
  if (Serial1.available() > 0) {
    String scannedUID = "";
    
    while (Serial1.available() > 0) {
      char incomingByte = Serial1.read(); 
      scannedUID += incomingByte;
      delay(2); 
    }
    
    scannedUID.trim();

    DateTime now = rtc.now();
    char timestamp[25];
    sprintf(timestamp, "%04d/%02d/%02d %02d:%02d:%02d", 
            now.year(), now.month(), now.day(), 
            now.hour(), now.minute(), now.second());

    Serial.print("[");
    Serial.print(timestamp);
    Serial.print("] UID: ");
    Serial.print(scannedUID);
    
    // Check the database and fire the hardware
    if (isCardAuthorized(scannedUID)) {
      Serial.println(" -> GRANTED");
      
      // Save to flash drive (true = Granted)
      logAccess(String(timestamp), scannedUID, true);
      
      grantAccess(); 
    } else {
      Serial.println(" -> DENIED");
      
      // Save to flash drive (false = Denied)
      logAccess(String(timestamp), scannedUID, false);
      
      denyAccess(); 
    }
  }
}