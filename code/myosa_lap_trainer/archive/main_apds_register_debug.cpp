// TEMPORARY APDS RGB/AMBIENT + IMU DIAGNOSTIC
// RESTORE FULL MVP FIRMWARE AFTER SENSOR CHARACTERIZATION.
//
// APDS9960: ambient light + RGB/color only (no proximity hover, no gesture).
// IMU: MPU6050 accel + gyro streamed alongside APDS for bring-up validation.

#include <Arduino.h>
#include <Wire.h>
#include <cmath>
#include <cstring>

#include "AccelAndGyro.h"
#include "LightProximityAndGesture.h"

constexpr unsigned long kSerialStartupMs = 500;
constexpr unsigned long kSamplePeriodMs = 40;
constexpr unsigned long kI2cSettleMs = 100;
constexpr unsigned long kCaptureMs = 5000;

constexpr uint8_t kApdsAddr = APDS9960_I2C_ADDRESS;
constexpr uint8_t kImuAddr = MPU6050_ADDRESS_AD0_HIGH;
constexpr uint8_t kOledAddr = 0x3C;

constexpr uint8_t STATUS_AVALID_MSK = 0x01u;  // APDS STATUS bit0: RGBC/PDATA valid

namespace {

LightProximityAndGesture apds;
AccelAndGyro imu;

bool g_apds_i2c = false;
bool g_apds_begin = false;
bool g_apds_als_rgb = false;
bool g_imu_begin = false;

uint8_t g_gain_index = 1;
const uint8_t kGainCodes[] = {AGAIN_1X, AGAIN_4X, AGAIN_16X, AGAIN_64X};
const char *const kGainLabels[] = {"1x", "4x", "16x", "64x"};

uint16_t g_baseline_clear = 0;
bool g_baseline_valid = false;

unsigned long g_sample_index = 0;
unsigned long g_next_sample_ms = 0;
float g_prev_acc_mag = 0.0f;
unsigned long g_prev_sample_ms = 0;
char g_event[24] = "";

struct RgbStats {
  bool valid = false;
  uint16_t clear_mean = 0;
  uint16_t clear_min = 0xFFFF;
  uint16_t clear_max = 0;
  uint16_t red_mean = 0;
  uint16_t green_mean = 0;
  uint16_t blue_mean = 0;
  float r_norm_mean = 0.0f;
  float g_norm_mean = 0.0f;
  float b_norm_mean = 0.0f;
  float clear_delta_mean = 0.0f;
  float occlusion_pct_mean = 0.0f;
};

RgbStats g_air;
RgbStats g_target;

void handleSerialDuringCapture();
void handleSerial();

void clearEvent() { g_event[0] = '\0'; }

void setEvent(const char *ev) {
  if (ev == nullptr) {
    clearEvent();
    return;
  }
  strncpy(g_event, ev, sizeof(g_event) - 1);
  g_event[sizeof(g_event) - 1] = '\0';
}

bool i2cProbe(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

void runI2cScan() {
  Serial.println(F("I2C scan:"));
  for (uint8_t addr = 1; addr < 127; ++addr) {
    if (i2cProbe(addr)) {
      Serial.print(F("  0x"));
      if (addr < 16) {
        Serial.print('0');
      }
      Serial.println(addr, HEX);
    }
  }
}

uint8_t readReg(uint8_t reg) {
  Wire.beginTransmission(kApdsAddr);
  Wire.write(reg);
  if (Wire.endTransmission(false) != 0) {
    return 0xFF;
  }
  if (Wire.requestFrom(kApdsAddr, static_cast<uint8_t>(1)) != 1) {
    return 0xFF;
  }
  return Wire.read();
}

uint16_t readReg16Le(uint8_t reg_lo) {
  const uint8_t lo = readReg(reg_lo);
  const uint8_t hi = readReg(static_cast<uint8_t>(reg_lo + 1u));
  if (lo == 0xFF && hi == 0xFF) {
    return 0xFFFF;
  }
  return static_cast<uint16_t>(lo) | (static_cast<uint16_t>(hi) << 8);
}

bool readRgbClear(uint16_t *clear, uint16_t *r, uint16_t *g, uint16_t *b) {
  if (clear == nullptr || r == nullptr || g == nullptr || b == nullptr) {
    return false;
  }
  *clear = readReg16Le(APDS9960_CDATAL);
  *r = readReg16Le(APDS9960_RDATAL);
  *g = readReg16Le(APDS9960_GDATAL);
  *b = readReg16Le(APDS9960_BDATAL);
  return *clear != 0xFFFF && *r != 0xFFFF && *g != 0xFFFF && *b != 0xFFFF;
}

void computeNorms(uint16_t r, uint16_t g, uint16_t b, float *rn, float *gn,
                  float *bn) {
  const float sum = static_cast<float>(r) + static_cast<float>(g) +
                    static_cast<float>(b);
  if (sum <= 0.0f) {
    *rn = *gn = *bn = 0.0f;
    return;
  }
  *rn = static_cast<float>(r) / sum;
  *gn = static_cast<float>(g) / sum;
  *bn = static_cast<float>(b) / sum;
}

const char *againLabel(uint8_t code) {
  switch (code) {
    case AGAIN_1X:
      return "1x";
    case AGAIN_4X:
      return "4x";
    case AGAIN_16X:
      return "16x";
    case AGAIN_64X:
      return "64x";
    default:
      return "?";
  }
}

bool initApds() {
  g_apds_begin = apds.begin();
  if (!g_apds_begin) {
    return false;
  }

  apds.disableGestureSensor();
  apds.disableProximitySensor();

  if (!apds.enableAmbientLightSensor(DISABLE)) {
    return false;
  }

  g_gain_index = 1;
  if (!apds.setAmbientLightGain(kGainCodes[g_gain_index])) {
    return false;
  }

  uint16_t clear = 0;
  uint16_t r = 0;
  uint16_t g = 0;
  uint16_t b = 0;
  g_apds_als_rgb = readRgbClear(&clear, &r, &g, &b);
  return g_apds_als_rgb;
}

bool initImu() {
  g_imu_begin = imu.begin(false);
  return g_imu_begin;
}

void printColumnLegend() {
  Serial.println(F("--- CSV column legend ---"));
  Serial.println(F("sample       = row number"));
  Serial.println(F("t_ms         = milliseconds since boot"));
  Serial.println(F("apds_ok      = 1 if APDS ALS/RGB path active"));
  Serial.println(F("imu_ok       = 1 if IMU initialized"));
  Serial.println(F("clear        = APDS clear channel raw (CDATAL/H)"));
  Serial.println(F("red/green/blue = APDS RGB raw counts"));
  Serial.println(F("r_norm/g_norm/b_norm = channel / (R+G+B)"));
  Serial.println(F("clear_delta  = clear - baseline_clear (signed)"));
  Serial.println(
      F("occlusion_pct = 100*(baseline_clear-clear)/baseline_clear when baseline set"));
  Serial.println(F("als_gain     = ambient gain code (0=1x..3=64x)"));
  Serial.println(F("ax,ay,az     = IMU acceleration (library units)"));
  Serial.println(F("gx,gy,gz     = IMU gyroscope (library units)"));
  Serial.println(F("acc_mag      = sqrt(ax^2+ay^2+az^2)"));
  Serial.println(F("gyro_mag     = sqrt(gx^2+gy^2+gz^2)"));
  Serial.println(F("jerk_proxy   = |acc_mag - prev_acc_mag| / dt_seconds"));
  Serial.println(
      F("event        = BASELINE_CAPTURED, TARGET_CAPTURED, GAIN_CHANGED, RESET, or blank"));
  Serial.println(F("-------------------------"));
}

void printCsvHeader() {
  Serial.println(
      F("sample,t_ms,apds_ok,imu_ok,clear,red,green,blue,r_norm,g_norm,b_norm,"
        "clear_delta,occlusion_pct,als_gain,ax,ay,az,gx,gy,gz,acc_mag,gyro_mag,"
        "jerk_proxy,event"));
}

void printHelp() {
  Serial.println(F("Commands:"));
  Serial.println(F("  h = help + column legend"));
  Serial.println(F("  r = reset stats / clear event"));
  Serial.println(F("  z = 5s open-air / room-light baseline"));
  Serial.println(F("  t = 5s covered / target / colored-tape baseline"));
  Serial.println(F("  p = print air vs target summary"));
  Serial.println(F("  g = cycle ambient gain 1x/4x/16x/64x"));
  Serial.println(F("  v = APDS register + mode dump"));
}

void printApdsDump() {
  const uint8_t id = readReg(APDS9960_ID);
  const uint8_t enable = readReg(APDS9960_ENABLE);
  const uint8_t status = readReg(APDS9960_STATUS);
  const uint8_t control = readReg(APDS9960_CONTROL);
  const uint16_t clear = readReg16Le(APDS9960_CDATAL);
  const uint16_t r = readReg16Le(APDS9960_RDATAL);
  const uint16_t g = readReg16Le(APDS9960_GDATAL);
  const uint16_t b = readReg16Le(APDS9960_BDATAL);

  Serial.println(F("# --- APDS dump ---"));
  Serial.print(F("ID(0x92)=0x"));
  Serial.println(id, HEX);

  Serial.print(F("ENABLE(0x80)=0x"));
  Serial.println(enable, HEX);
  if (enable != 0xFF) {
    Serial.print(F("  PON(bit0)="));
    Serial.println((enable & PON_EN_MSK) ? 1 : 0);
    Serial.print(F("  AEN(bit1)="));
    Serial.println((enable & AEN_EN_MSK) ? 1 : 0);
    Serial.print(F("  PEN(bit2)="));
    Serial.println((enable & PEN_EN_MSK) ? 1 : 0);
    Serial.print(F("  GEN(bit6)="));
    Serial.println((enable & GEN_EN_MSK) ? 1 : 0);
    const bool ideal =
        (enable & PON_EN_MSK) && (enable & AEN_EN_MSK) && !(enable & PEN_EN_MSK) &&
        !(enable & GEN_EN_MSK);
    Serial.print(F("  ALS_RGB_MODE_OK="));
    Serial.println(ideal ? 1 : 0);
  }

  Serial.print(F("STATUS(0x93)=0x"));
  Serial.println(status, HEX);
  Serial.print(F("  AVALID(bit0, RGBC data valid)="));
  Serial.println((status & STATUS_AVALID_MSK) ? 1 : 0);
  Serial.print(F("  AINT(bit4)="));
  Serial.println((status & 0x10u) ? 1 : 0);

  Serial.print(F("CONTROL(0x8F)=0x"));
  Serial.println(control, HEX);
  if (control != 0xFF) {
    const uint8_t again = control & ALS_GAIN_MSK;
    Serial.print(F("  AGAIN(bits1:0)="));
    Serial.print(again);
    Serial.print(F(" ("));
    Serial.print(againLabel(again));
    Serial.println(F(")"));
  }

  Serial.print(F("CDATAL/H clear="));
  Serial.println(clear);
  Serial.print(F("RDATAL/H red="));
  Serial.println(r);
  Serial.print(F("GDATAL/H green="));
  Serial.println(g);
  Serial.print(F("BDATAL/H blue="));
  Serial.println(b);

  Serial.print(F("library getAmbientLightGain="));
  Serial.println(g_apds_begin ? apds.getAmbientLightGain() : 255);
  Serial.println(F("# -----------------"));
}

bool captureRgbStats(RgbStats *out, const char *event_name) {
  if (out == nullptr) {
    return false;
  }

  RgbStats cap;
  uint64_t sum_clear = 0;
  uint64_t sum_r = 0;
  uint64_t sum_g = 0;
  uint64_t sum_b = 0;
  float sum_rn = 0.0f;
  float sum_gn = 0.0f;
  float sum_bn = 0.0f;
  float sum_clear_delta = 0.0f;
  float sum_occ_pct = 0.0f;
  uint32_t n = 0;

  const unsigned long t_end = millis() + kCaptureMs;
  while (static_cast<long>(millis() - t_end) < 0) {
    handleSerialDuringCapture();

    uint16_t clear = 0;
    uint16_t r = 0;
    uint16_t g = 0;
    uint16_t b = 0;
    if (!readRgbClear(&clear, &r, &g, &b)) {
      delay(kSamplePeriodMs);
      continue;
    }

    float rn = 0.0f;
    float gn = 0.0f;
    float bn = 0.0f;
    computeNorms(r, g, b, &rn, &gn, &bn);

    if (clear < cap.clear_min) {
      cap.clear_min = clear;
    }
    if (clear > cap.clear_max) {
      cap.clear_max = clear;
    }

    sum_clear += clear;
    sum_r += r;
    sum_g += g;
    sum_b += b;
    sum_rn += rn;
    sum_gn += gn;
    sum_bn += bn;

    const float clear_delta =
        g_baseline_valid ? static_cast<float>(clear) - static_cast<float>(g_baseline_clear)
                         : 0.0f;
    sum_clear_delta += clear_delta;

    float occ = 0.0f;
    if (g_baseline_valid && g_baseline_clear > 0) {
      occ = 100.0f * (static_cast<float>(g_baseline_clear) - static_cast<float>(clear)) /
            static_cast<float>(g_baseline_clear);
    }
    sum_occ_pct += occ;

    ++n;
    delay(kSamplePeriodMs);
  }

  if (n == 0) {
    return false;
  }

  cap.valid = true;
  cap.clear_mean = static_cast<uint16_t>(sum_clear / n);
  cap.red_mean = static_cast<uint16_t>(sum_r / n);
  cap.green_mean = static_cast<uint16_t>(sum_g / n);
  cap.blue_mean = static_cast<uint16_t>(sum_b / n);
  cap.r_norm_mean = sum_rn / static_cast<float>(n);
  cap.g_norm_mean = sum_gn / static_cast<float>(n);
  cap.b_norm_mean = sum_bn / static_cast<float>(n);
  cap.clear_delta_mean = sum_clear_delta / static_cast<float>(n);
  cap.occlusion_pct_mean = sum_occ_pct / static_cast<float>(n);

  *out = cap;
  setEvent(event_name);
  return true;
}

void printSummary() {
  Serial.println(F("# --- baseline vs target ---"));

  if (g_air.valid) {
    Serial.print(F("AIR  clear mean="));
    Serial.print(g_air.clear_mean);
    Serial.print(F(" min="));
    Serial.print(g_air.clear_min);
    Serial.print(F(" max="));
    Serial.println(g_air.clear_max);
    Serial.print(F("     RGB means R="));
    Serial.print(g_air.red_mean);
    Serial.print(F(" G="));
    Serial.print(g_air.green_mean);
    Serial.print(F(" B="));
    Serial.println(g_air.blue_mean);
    Serial.print(F("     norms r="));
    Serial.print(g_air.r_norm_mean, 3);
    Serial.print(F(" g="));
    Serial.print(g_air.g_norm_mean, 3);
    Serial.print(F(" b="));
    Serial.println(g_air.b_norm_mean, 3);
  } else {
    Serial.println(F("AIR  (not captured — run z)"));
  }

  if (g_target.valid) {
    Serial.print(F("TGT  clear mean="));
    Serial.print(g_target.clear_mean);
    Serial.print(F(" min="));
    Serial.print(g_target.clear_min);
    Serial.print(F(" max="));
    Serial.println(g_target.clear_max);
    Serial.print(F("     RGB means R="));
    Serial.print(g_target.red_mean);
    Serial.print(F(" G="));
    Serial.print(g_target.green_mean);
    Serial.print(F(" B="));
    Serial.println(g_target.blue_mean);
    Serial.print(F("     norms r="));
    Serial.print(g_target.r_norm_mean, 3);
    Serial.print(F(" g="));
    Serial.print(g_target.g_norm_mean, 3);
    Serial.print(F(" b="));
    Serial.println(g_target.b_norm_mean, 3);
    Serial.print(F("     clear_delta_mean="));
    Serial.print(g_target.clear_delta_mean, 1);
    Serial.print(F(" occlusion_pct_mean="));
    Serial.println(g_target.occlusion_pct_mean, 1);
  } else {
    Serial.println(F("TGT  (not captured — run t)"));
  }

  if (g_air.valid && g_target.valid) {
    const float occ = g_target.occlusion_pct_mean;
    if (occ > 30.0f) {
      Serial.println(F(">> APDS_OCCLUSION_STRONG"));
    } else if (occ >= 10.0f) {
      Serial.println(F(">> APDS_OCCLUSION_WEAK"));
    } else {
      Serial.println(F(">> APDS_OCCLUSION_NONE"));
    }

    const float dr = fabsf(g_target.r_norm_mean - g_air.r_norm_mean);
    const float dg = fabsf(g_target.g_norm_mean - g_air.g_norm_mean);
    const float db = fabsf(g_target.b_norm_mean - g_air.b_norm_mean);
    const float rgb_delta = fmaxf(dr, fmaxf(dg, db));

    if (rgb_delta >= 0.12f) {
      Serial.println(F(">> APDS_COLOR_SEPARATION_STRONG"));
    } else if (rgb_delta >= 0.05f) {
      Serial.println(F(">> APDS_COLOR_SEPARATION_WEAK"));
    } else {
      Serial.println(F(">> APDS_COLOR_SEPARATION_NONE"));
    }
  }

  Serial.println(F("# --------------------------"));
}

void cycleGain() {
  if (!g_apds_begin) {
    return;
  }
  g_gain_index = (g_gain_index + 1) % 4;
  apds.setAmbientLightGain(kGainCodes[g_gain_index]);
  setEvent("GAIN_CHANGED");
  Serial.print(F("# ALS gain -> "));
  Serial.println(kGainLabels[g_gain_index]);
}

void resetStats() {
  g_sample_index = 0;
  g_prev_acc_mag = 0.0f;
  g_prev_sample_ms = 0;
  clearEvent();
  setEvent("RESET");
  Serial.println(F("# stats reset"));
}

void captureBaselineZ() {
  Serial.println(F("# z: capture open / room light (5s)..."));
  if (captureRgbStats(&g_air, "BASELINE_CAPTURED")) {
    g_baseline_clear = g_air.clear_mean;
    g_baseline_valid = g_baseline_clear > 0;
    Serial.print(F("# baseline_clear="));
    Serial.println(g_baseline_clear);
  }
}

void captureBaselineT() {
  Serial.println(F("# t: capture covered / target / tape (5s)..."));
  captureRgbStats(&g_target, "TARGET_CAPTURED");
}

void handleSerialDuringCapture() {
  while (Serial.available() > 0) {
    Serial.read();
  }
}

void handleSerial() {
  while (Serial.available() > 0) {
    const char c = static_cast<char>(Serial.read());
    switch (c) {
      case 'h':
      case 'H':
        printHelp();
        printColumnLegend();
        break;
      case 'r':
      case 'R':
        resetStats();
        break;
      case 'z':
      case 'Z':
        captureBaselineZ();
        break;
      case 't':
      case 'T':
        captureBaselineT();
        break;
      case 'p':
      case 'P':
        printSummary();
        break;
      case 'g':
      case 'G':
        cycleGain();
        break;
      case 'v':
      case 'V':
        printApdsDump();
        break;
      default:
        break;
    }
  }
}

void printBootStatus() {
  Serial.println(g_apds_i2c ? F("APDS_I2C_OK") : F("APDS_I2C_FAIL"));
  Serial.println(g_apds_begin ? F("APDS_BEGIN_OK") : F("APDS_BEGIN_FAIL"));
  Serial.println(g_apds_als_rgb ? F("APDS_ALS_RGB_OK") : F("APDS_ALS_RGB_FAIL"));
  Serial.println(g_imu_begin ? F("IMU_BEGIN_OK") : F("IMU_BEGIN_FAIL"));
}

void printPhysicalTestPlan() {
  Serial.println();
  Serial.println(F("Physical test plan:"));
  Serial.println(F("  1. z: open room light, nothing covering APDS."));
  Serial.println(F("  2. Cover with finger/tool/dock target, send t."));
  Serial.println(F("  3. p: check clear drop and RGB change."));
  Serial.println(F("  4. Try white paper, black tape, foil, red/green/blue tape."));
  Serial.println(F("  5. g: cycle ambient gain if saturated or too dim."));
  Serial.println();
}

void streamSample(unsigned long t_ms) {
  const int apds_ok = (g_apds_begin && g_apds_als_rgb) ? 1 : 0;
  const int imu_ok = g_imu_begin ? 1 : 0;

  uint16_t clear = 0;
  uint16_t r = 0;
  uint16_t g = 0;
  uint16_t b = 0;
  if (apds_ok) {
    if (!readRgbClear(&clear, &r, &g, &b)) {
      clear = r = g = b = 0;
    }
  }

  float rn = 0.0f;
  float gn = 0.0f;
  float bn = 0.0f;
  computeNorms(r, g, b, &rn, &gn, &bn);

  const float clear_delta =
      g_baseline_valid ? static_cast<float>(clear) - static_cast<float>(g_baseline_clear)
                       : 0.0f;

  float occlusion_pct = 0.0f;
  if (g_baseline_valid && g_baseline_clear > 0) {
    occlusion_pct =
        100.0f * (static_cast<float>(g_baseline_clear) - static_cast<float>(clear)) /
        static_cast<float>(g_baseline_clear);
  }

  const uint8_t als_gain =
      g_apds_begin ? apds.getAmbientLightGain() : 0xFF;

  float ax = 0.0f;
  float ay = 0.0f;
  float az = 0.0f;
  float gx = 0.0f;
  float gy = 0.0f;
  float gz = 0.0f;
  if (imu_ok) {
    ax = imu.getAccelX(false);
    ay = imu.getAccelY(false);
    az = imu.getAccelZ(false);
    gx = imu.getGyroX(false);
    gy = imu.getGyroY(false);
    gz = imu.getGyroZ(false);
  }

  const float acc_mag = sqrtf(ax * ax + ay * ay + az * az);
  const float gyro_mag = sqrtf(gx * gx + gy * gy + gz * gz);

  float jerk_proxy = 0.0f;
  if (g_prev_sample_ms > 0) {
    const float dt_s =
        static_cast<float>(t_ms - g_prev_sample_ms) / 1000.0f;
    if (dt_s > 0.0f) {
      jerk_proxy = fabsf(acc_mag - g_prev_acc_mag) / dt_s;
    }
  }
  g_prev_acc_mag = acc_mag;
  g_prev_sample_ms = t_ms;

  Serial.print(g_sample_index++);
  Serial.print(',');
  Serial.print(t_ms);
  Serial.print(',');
  Serial.print(apds_ok);
  Serial.print(',');
  Serial.print(imu_ok);
  Serial.print(',');
  Serial.print(clear);
  Serial.print(',');
  Serial.print(r);
  Serial.print(',');
  Serial.print(g);
  Serial.print(',');
  Serial.print(b);
  Serial.print(',');
  Serial.print(rn, 3);
  Serial.print(',');
  Serial.print(gn, 3);
  Serial.print(',');
  Serial.print(bn, 3);
  Serial.print(',');
  Serial.print(clear_delta, 1);
  Serial.print(',');
  Serial.print(occlusion_pct, 1);
  Serial.print(',');
  Serial.print(als_gain);
  Serial.print(',');
  Serial.print(ax, 2);
  Serial.print(',');
  Serial.print(ay, 2);
  Serial.print(',');
  Serial.print(az, 2);
  Serial.print(',');
  Serial.print(gx, 2);
  Serial.print(',');
  Serial.print(gy, 2);
  Serial.print(',');
  Serial.print(gz, 2);
  Serial.print(',');
  Serial.print(acc_mag, 2);
  Serial.print(',');
  Serial.print(gyro_mag, 2);
  Serial.print(',');
  Serial.print(jerk_proxy, 2);
  Serial.print(',');
  Serial.println(g_event);

  if (g_event[0] != '\0' && strcmp(g_event, "RESET") != 0) {
    clearEvent();
  }
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(kSerialStartupMs);

  Serial.println();
  Serial.println(F("=== TEMPORARY APDS RGB/AMBIENT + IMU DIAGNOSTIC ==="));
  Serial.println(F("No proximity hover gate — ALS + RGB + IMU bring-up only."));

  Wire.begin();
  Wire.setClock(100000);
  delay(kI2cSettleMs);

  runI2cScan();

  Serial.print(F("APDS 0x39: "));
  g_apds_i2c = i2cProbe(kApdsAddr);
  Serial.println(g_apds_i2c ? F("seen") : F("missing"));

  Serial.print(F("IMU 0x69: "));
  Serial.println(i2cProbe(kImuAddr) ? F("seen") : F("missing"));

  Serial.print(F("OLED 0x3C: "));
  Serial.println(i2cProbe(kOledAddr) ? F("seen (unused)") : F("missing"));

  if (g_apds_i2c) {
    initApds();
  }
  initImu();

  printBootStatus();
  printPhysicalTestPlan();
  printHelp();
  printColumnLegend();
  printCsvHeader();

  g_next_sample_ms = millis();
}

void loop() {
  handleSerial();

  const unsigned long now = millis();
  if (static_cast<long>(now - g_next_sample_ms) < 0) {
    return;
  }
  g_next_sample_ms = now + kSamplePeriodMs;

  streamSample(now);
}
