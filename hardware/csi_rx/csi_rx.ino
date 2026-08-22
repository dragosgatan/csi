#include <WiFi.h>
#include <esp_wifi.h>

#define CHANNEL   6

// mac printed by the tx board on boot
uint8_t txMac[6] = {0x88, 0x13, 0xBF, 0x0D, 0xD0, 0x14};

volatile uint32_t rawCount = 0;
volatile uint32_t matchCount = 0;
uint8_t lastMac[6] = {0};

void onCsi(void *ctx, wifi_csi_info_t *info) {
  rawCount++;
  memcpy(lastMac, info->mac, 6);

  const int8_t *csi = info->buf;
  if (!csi || info->len <= 0) return;
  if (memcmp(info->mac, txMac, 6) != 0) return;
  matchCount++;

  // send everything raw, no math: timestamp,rssi,len,byte0;byte1;byte2;...
  Serial.printf("%lu,%d,%d,", millis(), info->rx_ctrl.rssi, info->len);
  for (int i = 0; i < info->len; i++) {
    Serial.print(csi[i]);
    if (i < info->len - 1) Serial.print(';');
  }
  Serial.println();
}

void onSniff(void *buf, wifi_promiscuous_pkt_type_t type) {}

void setup() {
  Serial.begin(921600);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();

  wifi_promiscuous_filter_t filter = {};
  filter.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA;

  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(onSniff);
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);

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
  //Serial.printf("# rx ready, ch=%u, own mac %s\n", ch, WiFi.macAddress().c_str());
  //Serial.println("# format: timestamp_ms,rssi,len,raw_bytes(semicolon-separated)");
}

void loop() {
  static uint32_t last = 0;
  if (millis() - last < 1000) return;
  last = millis();

  //heartbeat
  Serial.printf("# heartbeat raw=%u match=%u last=%02X:%02X:%02X:%02X:%02X:%02X\n",
                rawCount, matchCount,
                lastMac[0], lastMac[1], lastMac[2], lastMac[3], lastMac[4], lastMac[5]);
}