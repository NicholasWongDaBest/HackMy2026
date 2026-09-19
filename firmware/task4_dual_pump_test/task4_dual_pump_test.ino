/*
 * ============================================================
 * Challenge 4 - Dual Pump Hardware Test
 * ============================================================
 *
 * Pump 1:
 *   ESP32 GPIO25
 *      -> Existing Keyestudio single relay
 *      -> Pump 1
 *      -> Container 1 to Container 2
 *
 * Pump 2:
 *   ESP32 GPIO14
 *      -> IN1 / K1 of 2-channel relay
 *      -> Pump 2
 *      -> Container 3 to Container 4
 *
 * K2 / IN2:
 *   UNUSED
 *
 * Serial baud:
 *   9600
 *
 * Commands:
 *
 * Pump 1 ON:
 * {"cmd":"pump","pump":1,"state":"on"}
 *
 * Pump 1 OFF:
 * {"cmd":"pump","pump":1,"state":"off"}
 *
 * Pump 2 ON:
 * {"cmd":"pump","pump":2,"state":"on"}
 *
 * Pump 2 OFF:
 * {"cmd":"pump","pump":2,"state":"off"}
 *
 * SAFETY:
 * - Both pumps OFF during startup
 * - Maximum continuous run = 10 seconds
 * - Only ONE pump may run at a time
 *
 * IMPORTANT:
 * Pump 2's dual relay is configured ACTIVE LOW.
 * Pump 1's original relay remains ACTIVE HIGH.
 * ============================================================
 */

#include <Arduino.h>
#include <ArduinoJson.h>


// ============================================================
// PIN CONFIGURATION
// ============================================================

constexpr uint8_t PUMP1_RELAY_PIN = 25;
constexpr uint8_t PUMP2_RELAY_PIN = 14;


// ============================================================
// RELAY POLARITY
// ============================================================
//
// false = active HIGH
// true  = active LOW
//

// Original Keyestudio single relay
constexpr bool PUMP1_RELAY_ACTIVE_LOW = false;

// New 2-channel relay - K1 / IN1
constexpr bool PUMP2_RELAY_ACTIVE_LOW = true;


// ============================================================
// SAFETY SETTINGS
// ============================================================

constexpr unsigned long PUMP_MAX_RUN_MS = 10000UL;  // 10 seconds
constexpr size_t MAX_COMMAND_LENGTH = 200;


// ============================================================
// PUMP STRUCTURE
// ============================================================

struct PumpChannel {
  uint8_t id;
  uint8_t relayPin;
  bool activeLow;
  bool running;
  unsigned long startedAtMs;
};


// ============================================================
// PUMP OBJECTS
// ============================================================

PumpChannel pump1 = {
  1,
  PUMP1_RELAY_PIN,
  PUMP1_RELAY_ACTIVE_LOW,
  false,
  0
};

PumpChannel pump2 = {
  2,
  PUMP2_RELAY_PIN,
  PUMP2_RELAY_ACTIVE_LOW,
  false,
  0
};


// ============================================================
// SERIAL INPUT
// ============================================================

String inputLine;
bool inputOverflow = false;


// ============================================================
// RELAY LEVEL FUNCTIONS
// ============================================================

uint8_t onLevel(const PumpChannel& pump) {

  if (pump.activeLow) {
    return LOW;
  }

  return HIGH;
}


uint8_t offLevel(const PumpChannel& pump) {

  if (pump.activeLow) {
    return HIGH;
  }

  return LOW;
}


// ============================================================
// SERIAL STATUS OUTPUT
// ============================================================

void emitPumpStatus(
  const PumpChannel& pump,
  const char* reason
) {

  JsonDocument response;

  response["type"] = "pump_status";
  response["pump"] = pump.id;
  response["state"] = pump.running ? "on" : "off";
  response["reason"] = reason;

  serializeJson(response, Serial);

  Serial.println();
}


// ============================================================
// SERIAL ERROR OUTPUT
// ============================================================

void emitError(
  const char* code,
  const char* detail
) {

  JsonDocument response;

  response["type"] = "error";
  response["error"] = code;
  response["detail"] = detail;

  serializeJson(response, Serial);

  Serial.println();
}


// ============================================================
// FIND PUMP FROM ID
// ============================================================

PumpChannel* findPump(int pumpId) {

  if (pumpId == 1) {
    return &pump1;
  }

  if (pumpId == 2) {
    return &pump2;
  }

  return nullptr;
}


// ============================================================
// TURN PUMP OFF
// ============================================================

void turnPumpOff(
  PumpChannel& pump,
  const char* reason
) {

  digitalWrite(
    pump.relayPin,
    offLevel(pump)
  );


  bool wasRunning = pump.running;

  pump.running = false;
  pump.startedAtMs = 0;


  if (wasRunning) {

    emitPumpStatus(
      pump,
      reason
    );

  } else {

    emitPumpStatus(
      pump,
      "already_off"
    );
  }
}


// ============================================================
// TURN PUMP ON
// ============================================================

void turnPumpOn(PumpChannel& pump) {

  // Pump already running
  if (pump.running) {

    // Do NOT reset the timer.
    // This prevents repeated ON commands from bypassing
    // the 10-second safety timeout.

    emitPumpStatus(
      pump,
      "already_on"
    );

    return;
  }


  // ==========================================================
  // INTERLOCK
  //
  // Only one pump may run at a time.
  // ==========================================================

  if (pump.id == 1 && pump2.running) {

    turnPumpOff(
      pump2,
      "interlock"
    );
  }


  if (pump.id == 2 && pump1.running) {

    turnPumpOff(
      pump1,
      "interlock"
    );
  }


  // ==========================================================
  // ACTIVATE RELAY
  // ==========================================================

  digitalWrite(
    pump.relayPin,
    onLevel(pump)
  );


  pump.running = true;
  pump.startedAtMs = millis();


  emitPumpStatus(
    pump,
    "command"
  );
}


// ============================================================
// SET PUMP
// ============================================================

void setPump(
  PumpChannel& pump,
  bool turnOn
) {

  if (turnOn) {

    turnPumpOn(pump);

  } else {

    turnPumpOff(
      pump,
      "command"
    );
  }
}


// ============================================================
// HANDLE JSON COMMAND
// ============================================================

void handleCommand(const String& line) {

  JsonDocument command;


  // Parse incoming JSON
  DeserializationError parseError =
    deserializeJson(
      command,
      line
    );


  if (parseError) {

    emitError(
      "invalid_json",
      parseError.c_str()
    );

    return;
  }


  // Root must be JSON object
  if (!command.is<JsonObject>()) {

    emitError(
      "invalid_command",
      "JSON root must be an object"
    );

    return;
  }


  // ==========================================================
  // CHECK COMMAND
  // ==========================================================

  const char* commandName =
    command["cmd"] | "";


  if (
    strcmp(
      commandName,
      "pump"
    ) != 0
  ) {

    emitError(
      "invalid_command",
      "cmd must be pump"
    );

    return;
  }


  // ==========================================================
  // CHECK PUMP ID
  // ==========================================================

  if (!command["pump"].is<int>()) {

    emitError(
      "invalid_pump",
      "pump must be integer 1 or 2"
    );

    return;
  }


  int pumpId =
    command["pump"].as<int>();


  PumpChannel* pump =
    findPump(pumpId);


  if (pump == nullptr) {

    emitError(
      "invalid_pump",
      "pump must be 1 or 2"
    );

    return;
  }


  // ==========================================================
  // CHECK REQUESTED STATE
  // ==========================================================

  const char* requestedState =
    command["state"] | "";


  if (
    strcmp(
      requestedState,
      "on"
    ) == 0
  ) {

    setPump(
      *pump,
      true
    );

  }

  else if (
    strcmp(
      requestedState,
      "off"
    ) == 0
  ) {

    setPump(
      *pump,
      false
    );

  }

  else {

    emitError(
      "invalid_state",
      "state must be on or off"
    );
  }
}


// ============================================================
// READ SERIAL COMMANDS
// ============================================================

void readCommands() {

  while (Serial.available() > 0) {

    char received =
      static_cast<char>(
        Serial.read()
      );


    // ========================================================
    // NEWLINE = COMMAND COMPLETE
    // ========================================================

    if (received == '\n') {

      if (inputOverflow) {

        emitError(
          "command_too_long",
          "command exceeds 200 characters"
        );

      }

      else if (inputLine.length() > 0) {

        handleCommand(
          inputLine
        );
      }


      inputLine = "";
      inputOverflow = false;
    }


    // ========================================================
    // IGNORE CARRIAGE RETURN
    // ========================================================

    else if (received == '\r') {

      // Ignore
    }


    // ========================================================
    // STORE CHARACTER
    // ========================================================

    else if (
      !inputOverflow &&
      inputLine.length() < MAX_COMMAND_LENGTH
    ) {

      inputLine += received;
    }


    // ========================================================
    // COMMAND TOO LONG
    // ========================================================

    else {

      inputOverflow = true;
    }
  }
}


// ============================================================
// 10-SECOND SAFETY TIMEOUT
// ============================================================

void enforcePumpSafety(PumpChannel& pump) {

  if (!pump.running) {

    return;
  }


  unsigned long elapsed =
    millis() - pump.startedAtMs;


  if (
    elapsed >= PUMP_MAX_RUN_MS
  ) {

    turnPumpOff(
      pump,
      "safety_timeout"
    );
  }
}


// ============================================================
// CONFIGURE PUMP OFF AT STARTUP
// ============================================================

void configurePumpOff(PumpChannel& pump) {

  /*
   * Load OFF level before enabling OUTPUT.
   *
   * This helps reduce relay glitches during ESP32 startup.
   */

  digitalWrite(
    pump.relayPin,
    offLevel(pump)
  );


  pinMode(
    pump.relayPin,
    OUTPUT
  );


  digitalWrite(
    pump.relayPin,
    offLevel(pump)
  );


  pump.running = false;
  pump.startedAtMs = 0;
}


// ============================================================
// SETUP
// ============================================================

void setup() {

  /*
   * Configure pumps OFF before starting Serial.
   */

  configurePumpOff(pump1);
  configurePumpOff(pump2);


  // Serial communication
  Serial.begin(9600);


  inputLine.reserve(
    MAX_COMMAND_LENGTH
  );


  // Give ESP32 time to finish booting
  delay(1500);


  // ==========================================================
  // READY MESSAGE
  // ==========================================================

  JsonDocument ready;

  ready["type"] = "status";
  ready["status"] = "ready";

  serializeJson(
    ready,
    Serial
  );

  Serial.println();


  // ==========================================================
  // REPORT INITIAL PUMP STATES
  // ==========================================================

  emitPumpStatus(
    pump1,
    "boot"
  );


  emitPumpStatus(
    pump2,
    "boot"
  );
}


// ============================================================
// MAIN LOOP
// ============================================================

void loop() {

  // Read incoming commands
  readCommands();


  // Enforce independent safety timers
  enforcePumpSafety(pump1);
  enforcePumpSafety(pump2);


  delay(2);
}