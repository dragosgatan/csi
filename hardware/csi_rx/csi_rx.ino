/* archived file not used anywhere */


#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_wifi.h>
#include "../secrets.h"

#define CHANNEL   11
#define NODE_ID   4

// mac printed by the tx board on boot
uint8_t txMac[6] = {0x88, 0x13, 0xBF, 0x0D, 0xD0, 0x14};


WiFiUDP udp;

volatile uint32_t rawCount = 0;
volatile uint32_t matchCount = 0;
uint8_t lastMac[6] = {0};



// reusable buffer for building each UDP payload
char payload[1400];

void onCsi(void *ctx, wifi_csi_info_t *info) {
  rawCount++;
  memcpy(lastMac, info->mac, 6);

  const int8_t *csi = info->buf;
  if (!csi || info->len <= 0) return;
  if (memcmp(info->mac, txMac, 6) != 0) return;
  matchCount++;

  int pos = snprintf(payload, sizeof(payload), "%u,%lu,%d,%d,",
                      NODE_ID, millis(), info->rx_ctrl.rssi, info->len);

  udp.beginPacket(LAPTOP_IP, LAPTOP_PORT);
  udp.write((const uint8_t*)payload, pos);
  udp.write((const uint8_t*)csi, info->len);
  udp.endPacket();
}

void onSniff(void *buf, wifi_promiscuous_pkt_type_t type) {}

void setup() {
  Serial.begin(115200);
  delay(300);

  Serial.print("# connecting to ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  Serial.print("# connected, my IP: ");
  Serial.println(WiFi.localIP());
  Serial.print("# node id: ");
  Serial.println(NODE_ID);
  Serial.print("# sending CSI to ");
  Serial.print(LAPTOP_IP);
  Serial.print(":");
  Serial.println(LAPTOP_PORT);

  udp.begin(LAPTOP_PORT);

  wifi_promiscuous_filter_t filter = {};
  filter.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA;

  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(onSniff);

  wifi_csi_config_t cfg = {};
  cfg.lltf_en = true;
  cfg.htltf_en = true;
  cfg.ltf_merge_en = true;
  cfg.channel_filter_en = true;

  esp_wifi_set_csi_config(&cfg);
  esp_wifi_set_csi_rx_cb(onCsi, NULL);
  esp_wifi_set_csi(true);

  uint8_t ch;
  wifi_second_chan_t sec;
  esp_wifi_get_channel(&ch, &sec);
  Serial.printf("# csi ready, ch=%u (make sure this matches your TX board's channel)\n", ch);
}

void loop() {
  static uint32_t last = 0;
  if (millis() - last < 1000) return;
  last = millis();

  // heartbeat 
  Serial.printf("# heartbeat raw=%u match=%u last=%02X:%02X:%02X:%02X:%02X:%02X\n",
                rawCount, matchCount,
                lastMac[0], lastMac[1], lastMac[2], lastMac[3], lastMac[4], lastMac[5]);
}
