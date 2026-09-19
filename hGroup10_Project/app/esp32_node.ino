/*
 * hGroup10 ESP32 sensor and pump node.
 *
 * Sensors -> newline-delimited JSON -> Raspberry Pi/MySQL/dashboard.
 * Raspberry Pi -> PUMP_ON/PUMP_OFF -> ESP32 IO25 -> relay -> pump.
 *
 * DIVISION OF LABOUR
 * The Raspberry Pi owns the irrigation decision and reads the RS485 soil
 * probe itself -- that probe reports calibrated moisture, temperature and
 * EC, so nothing here needs a scaling factor to make it look right.
 * This board contributes the channels the Pi physically cannot read (it
 * has no ADC) and drives the relay on command.
 *
 * SAFETY
 * The ESP32 has the final 10-second cutoff. Even if the Pi or dashboard
 * fails after PUMP_ON, the relay is returned to OFF. Because the cap
 * applies from the moment the pump starts, a lost USB cable cannot leave
 * the pump running for more than PUMP_MAX_RUN_MS either -- no keepalive
 * from the Pi is required.
 */
#include <Arduino.h>
#include <dht11.h>

#define DHT11PIN       17
#define LIGHTPIN       34
#define WATERLEVELPIN  33
#define RAINWATERPIN   35
#define RELAYPIN       25
// Soil moisture is deliberately NOT read here. The RS485 probe on the Pi
// owns that measurand and reports real percent, so the kit's analog pin
// would only add a second, uncalibrated "moisture" to argue with.

const unsigned long SAMPLE_INTERVAL_MS = 60000UL;
const unsigned long PUMP_MAX_RUN_MS = 10000UL;
const char* POSITION = "zone-2-canopy";   // distinct from the probe's zone-1

// This board's relay energises on HIGH, so RELAY_ACTIVE_LOW stays false.
// If the relay LED is on while the dashboard says STOPPED, the module is
// wired the other way round -- set this true and re-upload.
const bool RELAY_ACTIVE_LOW = false;
const uint8_t PUMP_ON_LEVEL = RELAY_ACTIVE_LOW ? LOW : HIGH;
const uint8_t PUMP_OFF_LEVEL = RELAY_ACTIVE_LOW ? HIGH : LOW;

const float ADC_FULL_SCALE = 4095.0;

dht11 DHT11;
unsigned long lastSample = 0;
unsigned long pumpStartedAt = 0;
bool pumpRunning = false;
String commandBuffer;

float clampPercent(float value) {
  if (value < 0.0) return 0.0;
  if (value > 100.0) return 100.0;
  return value;
}

// Percent of ADC full scale, and nothing else. No multiplier: a number we
// cannot explain the origin of is worse than a raw one we can.
float percentOfFullScale(int raw) {
  return clampPercent((raw / ADC_FULL_SCALE) * 100.0);
}

void emitReading(const char* sensorType, float value) {
  Serial.print("{\"sensor_position\":\"");
  Serial.print(POSITION);
  Serial.print("\",\"sensor_type\":\"");
  Serial.print(sensorType);
  Serial.print("\",\"sensor_value\":");
  Serial.print(value, 2);
  Serial.println("}");
}

void reportPump(const char* reason) {
  Serial.print("{\"type\":\"pump\",\"state\":\"");
  Serial.print(pumpRunning ? "on" : "off");
  Serial.print("\",\"reason\":\"");
  Serial.print(reason);
  Serial.println("\"}");
}

void setPump(bool turnOn, const char* reason) {
  digitalWrite(RELAYPIN, turnOn ? PUMP_ON_LEVEL : PUMP_OFF_LEVEL);
  pumpRunning = turnOn;
  if (turnOn) pumpStartedAt = millis();
  reportPump(reason);
}

void handleCommand(String command) {
  command.trim();
  command.toUpperCase();

  if (command == "PUMP_ON") {
    setPump(true, "command");
  } else if (command == "PUMP_OFF") {
    setPump(false, "command");
  } else if (command == "PUMP_STATUS") {
    reportPump("status_request");
  } else if (command.length() > 0) {
    Serial.print("{\"type\":\"error\",\"message\":\"unknown command: ");
    Serial.print(command);
    Serial.println("\"}");
  }
}

void readCommands() {
  while (Serial.available() > 0) {
    char received = Serial.read();
    if (received == '\n' || received == '\r') {
      if (commandBuffer.length() > 0) {
        handleCommand(commandBuffer);
        commandBuffer = "";
      }
    } else if (commandBuffer.length() < 50) {
      commandBuffer += received;
    }
  }
}

void sampleAndReport() {
  // A failed read emits NOTHING. Never a default, never a zero: a missing
  // row is honest, a fabricated one is not.
  int dhtResult = DHT11.read(DHT11PIN);
  if (dhtResult == DHTLIB_OK) {
    emitReading("air_temperature", (float)DHT11.temperature);
    emitReading("humidity", (float)DHT11.humidity);
  } else {
    Serial.print("{\"type\":\"error\",\"message\":\"DHT11 read failed: ");
    Serial.print(dhtResult);
    Serial.println("\"}");
  }

  emitReading("light",       percentOfFullScale(analogRead(LIGHTPIN)));
  emitReading("water_level", percentOfFullScale(analogRead(WATERLEVELPIN)));
  emitReading("rainfall",    percentOfFullScale(analogRead(RAINWATERPIN)));
}

void setup() {
  Serial.begin(9600);

  pinMode(DHT11PIN, INPUT);
  pinMode(LIGHTPIN, INPUT);
  pinMode(WATERLEVELPIN, INPUT);
  pinMode(RAINWATERPIN, INPUT);

  pinMode(RELAYPIN, OUTPUT);
  digitalWrite(RELAYPIN, PUMP_OFF_LEVEL);

  delay(1500);
  Serial.println("{\"type\":\"system\",\"status\":\"ready\"}");
  reportPump("boot");

  lastSample = millis() - SAMPLE_INTERVAL_MS;
}

void loop() {
  readCommands();

  unsigned long now = millis();
  if (pumpRunning && now - pumpStartedAt >= PUMP_MAX_RUN_MS) {
    setPump(false, "safety_timeout");
  }

  if (now - lastSample >= SAMPLE_INTERVAL_MS) {
    lastSample = now;
    sampleAndReport();
  }
}
