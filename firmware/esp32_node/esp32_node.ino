/*
 * ESP32 farm node -- hGroup10 "Save the Farm"
 *
 * Wired per the Keyestudio KS0567 assembly guide. Two jobs:
 *   1. read the kit's on-board sensors and stream them to the Pi as JSON
 *   2. drive the irrigation relay on command from the Pi
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

const char* POSITION = "zone-2-canopy";
const float ADC_FULL_SCALE = 4095.0;

dht11 DHT11;
unsigned long lastSample    = 0;
unsigned long pumpStartedMs = 0;
unsigned long lastCommandMs = 0;
bool   pumpOn = false;
String inputLine = "";

// ---- relay ------------------------------------------------------------
void relayWrite(bool on) {
  digitalWrite(RELAYPIN, (on == RELAY_ACTIVE_HIGH) ? HIGH : LOW);
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

// Raw ADC counts mean nothing to a judge. Convert to % of full scale.
float percentOfFullScale(int raw) {
  float pct = (raw / ADC_FULL_SCALE) * 100.0;
  if (pct < 0.0)   pct = 0.0;
  if (pct > 100.0) pct = 100.0;
  return pct;
}

void sampleAndReport() {
  // A failed read emits NOTHING. Never a default, never a zero: a missing
  // row is honest, a fabricated one is not.
  int dhtResult = DHT11.read(DHT11PIN);
  if (dhtResult == DHTLIB_OK) {
    emitReading("air_temperature", (float)DHT11.temperature);
    emitReading("humidity", (float)DHT11.humidity);
  } else {
    Serial.print("{\"node\":\"esp32\",\"error\":\"dht11 read failed, code ");
    Serial.print(chk);
    Serial.println("\"}");
  }

  emitReading("light",       percentOfFullScale(analogRead(LIGHTPIN)));
  emitReading("water_level", percentOfFullScale(analogRead(WATERLEVELPIN)));
  emitReading("rainfall",    percentOfFullScale(analogRead(RAINWATERPIN)));
}

// ---- watchdog ---------------------------------------------------------
void enforceSafety() {
  if (!pumpOn) return;

  if (millis() - pumpStartedMs > PUMP_MAX_RUN_MS) {
    setPump(false, "max_runtime");
    return;
  }
  if (millis() - lastCommandMs > COMMAND_TIMEOUT_MS) {
    setPump(false, "link_lost");
  }
}

// ---- lifecycle --------------------------------------------------------
void setup() {
  Serial.begin(115200);

  pinMode(RELAYPIN, OUTPUT);
  relayWrite(false);                 // pump off before anything else

  pinMode(LIGHTPIN, INPUT);
  pinMode(WATERLEVELPIN, INPUT);
  pinMode(RAINWATERPIN, INPUT);

  inputLine.reserve(128);
  delay(1500);                       // DHT11 needs ~1s after power-up
  Serial.println("{\"node\":\"esp32\",\"status\":\"boot\",\"pump\":\"off\"}");
  lastSample = millis() - SAMPLE_INTERVAL_MS;   // sample immediately
}

void loop() {
  // 1. commands first -- never leave the pump waiting behind a sensor read
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      handleCommand(inputLine);
      inputLine = "";
    } else if (c != '\r') {
      if (inputLine.length() < 200) inputLine += c;   // cap: ignore junk floods
    }
  }

  // 2. safety, every pass
  enforceSafety();

  // 3. sampling. Subtraction handles the ~49-day millis() rollover.
  unsigned long now = millis();
  if (now - lastSample >= SAMPLE_INTERVAL_MS) {
    lastSample = now;
    sampleAndReport();
  }
}
