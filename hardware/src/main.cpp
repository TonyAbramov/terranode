#include <Arduino.h>
#include "FS.h"
#include "SD_MMC.h"

#define USER_LED_PIN 21
#define LED_ON  LOW
#define LED_OFF HIGH

#define EBYTE_RX_PIN D7
#define EBYTE_TX_PIN D6

#define LOG_FILE "/terranode_log.txt"

#define RX_IDLE_MS 30

HardwareSerial LoRaSerial(1);

bool sdReady = false;

unsigned long lastBlinkTime = 0;
const unsigned long heartbeatInterval = 500;
bool ledState = false;

unsigned long rxFlashUntil = 0;             
const unsigned long rxFlashDuration = 1200; 
const unsigned long rxFlashInterval = 100;  

unsigned long lastStatusTime = 0;
const unsigned long statusInterval = 3000; 

long expectedSeq = -1;
unsigned long totalExpected = 0;
unsigned long totalReceived = 0;

bool parseSequence(const String &msg, long &seqOut) {
  int i = 0;
  while (i < (int)msg.length() && isDigit(msg[i])) i++;
  if (i == 0) return false;
  seqOut = msg.substring(0, i).toInt();
  return true;
}

void logToSD(const String &message) {
  if (!sdReady) return;

  unsigned long ms = millis();
  unsigned long totalSec = ms / 1000;
  unsigned long hh = totalSec / 3600;
  unsigned long mm = (totalSec % 3600) / 60;
  unsigned long ss = totalSec % 60;

  char timestamp[16];
  snprintf(timestamp, sizeof(timestamp), "%02lu:%02lu:%02lu", hh, mm, ss);

  File f = SD_MMC.open(LOG_FILE, FILE_APPEND);
  if (f) {
    f.printf("[+%s] %s\n", timestamp, message.c_str());
    f.close();
  } else {
    Serial.println("[SD] Failed to open log file for writing!");
  }
}

void setup() {
  pinMode(USER_LED_PIN, OUTPUT);
  digitalWrite(USER_LED_PIN, LED_OFF);

  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) {
    delay(10);
  }

  Serial.println("\n=============================");
  Serial.println(" TerraNode: Ebyte UART Gateway ");
  Serial.println("===============================");

  LoRaSerial.begin(9600, SERIAL_8N1, EBYTE_RX_PIN, EBYTE_TX_PIN);

  Serial.println("[SYSTEM] Hardware Serial1 initialized on D6(TX) and D7(RX)");
  Serial.println("[SYSTEM] Ebyte module configured in Transparent Mode (M0=0, M1=0)");

  SD_MMC.setPins(7, 9, 8);
  if (SD_MMC.begin("/sdcard", true)) {
    sdReady = true;
    Serial.println("[SD] Card mounted successfully.");

    int bootNumber = 0;
    File cnt = SD_MMC.open("/boot_count.txt", FILE_READ);
    if (cnt) {
      bootNumber = cnt.parseInt();
      cnt.close();
    }
    bootNumber++;
    File cntWrite = SD_MMC.open("/boot_count.txt", FILE_WRITE);
    if (cntWrite) {
      cntWrite.print(bootNumber);
      cntWrite.close();
    }

    logToSD("=== TerraNode boot #" + String(bootNumber) + " ===");
  } else {
    sdReady = false;
    Serial.println("[SD] Card not found or mount error - SD logging disabled.");
  }

  Serial.println("Waiting for incoming radio packets...\n");
}

void loop() {
  unsigned long now = millis();
  bool flashing = now < rxFlashUntil;
  unsigned long currentInterval = flashing ? rxFlashInterval : heartbeatInterval;

  if (now - lastBlinkTime >= currentInterval) {
    lastBlinkTime = now;
    ledState = !ledState;
    digitalWrite(USER_LED_PIN, ledState ? LED_ON : LED_OFF);
  }

  if (millis() - lastStatusTime >= statusInterval) {
    lastStatusTime = millis();
    Serial.println("[STATUS] TerraNode: Ebyte UART Gateway - alive, waiting for radio packets...");
  }

  static uint8_t rxBuf[256];
  static size_t rxLen = 0;
  static unsigned long lastRxByteTime = 0;

  while (LoRaSerial.available() && rxLen < sizeof(rxBuf)) {
    rxBuf[rxLen++] = LoRaSerial.read();
    lastRxByteTime = millis();
  }

  if (rxLen > 0 && (rxLen >= sizeof(rxBuf) || millis() - lastRxByteTime > RX_IDLE_MS)) {
    int rssiDbm = -(256 - rxBuf[rxLen - 1]);
    String incomingPacket;
    for (size_t i = 0; i + 1 < rxLen; i++) incomingPacket += (char)rxBuf[i];
    incomingPacket.trim();
    rxLen = 0;

    String rssiInfo = " RSSI=" + String(rssiDbm) + "dBm";

    String pdrInfo = "";
    long seq;
    if (parseSequence(incomingPacket, seq)) {
      if (expectedSeq == -1) {
        totalExpected += 1;
      } else {
        long gap = seq - expectedSeq;
        if (gap < 0) gap = 0; 
        totalExpected += gap + 1;
      }
      totalReceived += 1;
      expectedSeq = seq + 1;

      float pdr = (totalExpected > 0) ? (100.0f * totalReceived / totalExpected) : 0.0f;
      pdrInfo = " PDR=" + String(pdr, 1) + "%(" + String(totalReceived) + "/" + String(totalExpected) + ")";
    }

    Serial.print(">>> [LORA RX]: ");
    Serial.print(incomingPacket);
    Serial.print(rssiInfo);
    Serial.println(pdrInfo);
    logToSD("RX: " + incomingPacket + rssiInfo + pdrInfo);

    rxFlashUntil = millis() + rxFlashDuration;
  }

  if (Serial.available()) {
    String outgoingCommand = Serial.readStringUntil('\n');

    LoRaSerial.println(outgoingCommand);

    Serial.print("<<< [LORA TX]: ");
    Serial.println(outgoingCommand);
    logToSD("TX: " + outgoingCommand);
  }
}
