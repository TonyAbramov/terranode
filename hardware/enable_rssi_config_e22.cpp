#include <Arduino.h>
#include "LoRa_E22.h"

#define EBYTE_RX_PIN D7
#define EBYTE_TX_PIN D6
#define M0_PIN D2
#define M1_PIN D3

HardwareSerial LoRaSerial(1);
LoRa_E22 e22(&LoRaSerial, -1, M0_PIN, M1_PIN);

void printCfg(const char *tag, const Configuration &cfg) {
  Serial.print(tag);
  Serial.print(" ADDH=");        Serial.print(cfg.ADDH, HEX);
  Serial.print(" ADDL=");        Serial.print(cfg.ADDL, HEX);
  Serial.print(" NETID=");       Serial.print(cfg.NETID, HEX);
  Serial.print(" CHAN=");        Serial.print(cfg.CHAN);
  Serial.print(" uartBaud=");    Serial.print((int)cfg.SPED.uartBaudRate);
  Serial.print(" parity=");      Serial.print((int)cfg.SPED.uartParity);
  Serial.print(" airRate=");     Serial.print((int)cfg.SPED.airDataRate);
  Serial.print(" fixedTx=");     Serial.print((int)cfg.TRANSMISSION_MODE.fixedTransmission);
  Serial.print(" enableRSSI=");  Serial.println((int)cfg.TRANSMISSION_MODE.enableRSSI);
}

void setup() {
  Serial.begin(115200);
  unsigned long t0 = millis();
  while (!Serial && millis() - t0 < 3000) delay(10);

  LoRaSerial.begin(9600, SERIAL_8N1, EBYTE_RX_PIN, EBYTE_TX_PIN);

  Serial.println("\n=== TerraNode: RSSI Configuration Utility (E22) ===");
  delay(1500);

  e22.begin();

  ResponseStructContainer c = e22.getConfiguration();
  Serial.print("Reading configuration: ");
  Serial.println(c.status.getResponseDescription());

  if (c.status.code != E22_SUCCESS) {
    Serial.println("\nError: Module did not respond.");
    c.close();
    return;
  }

  Configuration configuration = *(Configuration *)c.data;
  printCfg("[BEFORE] ", configuration);

  configuration.SPED.uartBaudRate = UART_BPS_9600;
  configuration.SPED.uartParity = MODE_00_8N1;
  configuration.TRANSMISSION_MODE.fixedTransmission = FT_TRANSPARENT_TRANSMISSION;
  configuration.TRANSMISSION_MODE.enableRSSI = RSSI_ENABLED;
  
  ResponseStatus rs = e22.setConfiguration(configuration, WRITE_CFG_PWR_DWN_SAVE);
  Serial.print("Writing configuration: ");
  Serial.println(rs.getResponseDescription());
  c.close();

  delay(500);

  ResponseStructContainer c2 = e22.getConfiguration();
  Serial.print("Verification read: ");
  Serial.println(c2.status.getResponseDescription());
  
  if (c2.status.code == E22_SUCCESS) {
    Configuration confirmed = *(Configuration *)c2.data;
    printCfg("[AFTER]  ", confirmed);
    if ((int)confirmed.TRANSMISSION_MODE.enableRSSI == (int)RSSI_ENABLED) {
      Serial.println("\nStatus: RSSI successfully enabled and saved.");
    } else {
      Serial.println("\nError: RSSI is still disabled.");
    }
  }
  c2.close();
}

void loop() {
}
