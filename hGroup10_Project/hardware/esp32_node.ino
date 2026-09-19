/*
 * ESP32 canopy sensor node -- hGroup10 "Save the Farm"
 *
 * Reads the Keyestudio KS0567 on-board sensors and emits ONE JSON object
 * per reading, newline-delimited, over USB serial to the Raspberry Pi.
 *
 * Why serial and not WiFi/MQTT:
 *   The Pi is the only thing that talks to Farm Central. This board is a
 *   sensor, not a network peer. A USB cable cannot be knocked off the
 *   venue WiFi, needs no SSID, no broker, no routing between subnets --
 *   and the board is plugged into the Pi for power anyway.
 *
 * Design rules, mirroring farm/sensors.py on the Pi:
 *   - a failed read emits NOTHING. We never substitute a default, a last
 *     known value, or a zero. A missing row is honest; a fake row is not.
 *   - no timestamp is sent. The board has no clock; the Pi stamps rows
 *     with its own time, which is the only clock worth trusting here.
 *   - no delay() in loop(). The sampler is millis()-driven so the board
 *     stays responsive and the interval does not drift with read time.
 *
 * Pin map is the KS0567 factory wiring (see resource/arduino codes).
 * Library: dht11 (resource/arduino codes/libraries/Dht11.zip)
 *
 * Upload: Arduino IDE -> board "ESP32 Dev Module" -> 115200 baud.
 */
#include <dht11.h>

#define DHT11PIN       17   // digital: air temperature + humidity
#define LIGHTPIN       34   // ADC1: photoresistor
#define WATERLEVELPIN  33   // ADC1: tank level
#define RAINWATERPIN   35   // ADC1: steam / rainfall

// Must match POLL_INTERVAL_S on the Pi (brief: poll every 1 minute).
const unsigned long SAMPLE_INTERVAL_MS = 60000UL;

// Where this board physically sits. Must differ from the RS485 probe's
// SENSOR_POSITION so the dashboard can tell the two nodes apart.
const char* POSITION = "zone-2-canopy";

// ADC is 12-bit on the ESP32: 0..4095 maps to 0..100 %.
const float ADC_FULL_SCALE = 4095.0;

dht11 DHT11;
unsigned long lastSample = 0;

void setup() {
  Serial.begin(115200);
  pinMode(LIGHTPIN, INPUT);
  pinMode(WATERLEVELPIN, INPUT);
  pinMode(RAINWATERPIN, INPUT);

  delay(1500);  // DHT11 needs ~1s after power-up before its first read
  Serial.println("{\"node\":\"esp32\",\"status\":\"boot\"}");
  lastSample = millis() - SAMPLE_INTERVAL_MS;  // sample immediately
}

// Emit one reading as a JSON object the Pi's validator already accepts:
//   farm/validation.py -> validate_sensor_message()
void emit(const char* sensorType, float value) {
  Serial.print("{\"sensor_position\":\"");
  Serial.print(POSITION);
  Serial.print("\",\"sensor_type\":\"");
  Serial.print(sensorType);
  Serial.print("\",\"sensor_value\":");
  Serial.print(value, 2);
  Serial.println("}");
}

// Raw ADC counts mean nothing to a judge and nothing to an agronomist.
// Convert to a percentage of full scale and say so in the units.
float percentOfFullScale(int raw) {
  float pct = (raw / ADC_FULL_SCALE) * 100.0;
  if (pct < 0.0)   pct = 0.0;
  if (pct > 100.0) pct = 100.0;
  return pct;
}

void sampleAndReport() {
  // --- DHT11: digital, and it fails often enough to matter ------------
  int chk = DHT11.read(DHT11PIN);
  if (chk == 0) {                       // DHTLIB_OK
    emit("air_temperature", (float)DHT11.temperature);
    emit("humidity",        (float)DHT11.humidity);
  } else {
    // Checksum or timeout. Report the fault, emit no reading.
    Serial.print("{\"node\":\"esp32\",\"error\":\"dht11 read failed, code ");
    Serial.print(chk);
    Serial.println("\"}");
  }

  // --- Analog channels ------------------------------------------------
  emit("light",       percentOfFullScale(analogRead(LIGHTPIN)));
  emit("water_level", percentOfFullScale(analogRead(WATERLEVELPIN)));
  emit("rainfall",    percentOfFullScale(analogRead(RAINWATERPIN)));
}

void loop() {
  unsigned long now = millis();
  // Subtraction handles the ~49-day millis() rollover correctly.
  if (now - lastSample >= SAMPLE_INTERVAL_MS) {
    lastSample = now;
    sampleAndReport();
  }
}
