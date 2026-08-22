#include <WiFi.h>
#include <esp_wifi.h>
#include <math.h>

#define CHANNEL   6

// mac printed by the tx board on boot
uint8_t txMac[6] = {0x88, 0x13, 0xBF, 0x0D, 0xD0, 0x14};

#define SC_FIRST  6
#define SC_LAST   58
#define ALPHA     0.03    
#define BETA      0.25
#define THRESHOLD 0.22
#define WARMUP    150

float baseline[64];
bool haveBaseline = false;
volatile float level = 0;
volatile uint32_t count = 0;

volatile uint32_t rawCount = 0;   
volatile uint32_t matchCount = 0; 
uint8_t lastMac[6] = {0};

void onCsi(void *ctx, wifi_csi_info_t *info) {
  rawCount++;
  memcpy(lastMac, info->mac, 6);

  const int8_t *csi = info->buf;
  if (!csi || info->len < (SC_LAST + 1) * 2) return;
  if (memcmp(info->mac, txMac, 6) != 0) return;
  matchCount++;

  float sum = 0;
  int n = 0;
  for (int i = SC_FIRST; i <= SC_LAST; i++) {
    float im = csi[i * 2];
    float re = csi[i * 2 + 1];
    float amp = sqrtf(re * re + im * im);
    if (!haveBaseline) {
      baseline[i] = amp;
      continue;
    }
    sum += fabsf(amp - baseline[i]) / (baseline[i] + 1.0);
    baseline[i] += ALPHA * (amp - baseline[i]);
    n++;
  }

  if (!haveBaseline) {
    haveBaseline = true;
    return;
  }
  level += BETA * (sum / n - level);
  count++;
}

void onSniff(void *buf, wifi_promiscuous_pkt_type_t type) {}

void setup() {
  Serial.begin(115200);
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
  Serial.printf("rx ready, ch=%u, own mac %s\n", ch, WiFi.macAddress().c_str());
}

void loop() {
  static uint32_t last = 0;
  if (millis() - last < 200) return;
  last = millis();

  float v = level;
  uint32_t c = count;
  if (c < WARMUP) {
    Serial.printf("calibrating %u/%u  raw=%u match=%u  last=%02X:%02X:%02X:%02X:%02X:%02X\n",
                  c, WARMUP, rawCount, matchCount,
                  lastMac[0], lastMac[1], lastMac[2], lastMac[3], lastMac[4], lastMac[5]);
    return;
  }
  Serial.printf("%.3f %s\n", v, v > THRESHOLD ? "MOTION" : "still");
}
