// MYOSA Laparoscopic Trainer — MVP firmware with performance scoring
//
// APDS9960: ambient clear-channel occlusion for target-zone presence (not proximity).

#include <Arduino.h>
#include <Wire.h>
#include <cmath>
#include <cstring>

#include "esp_log.h"

#include "AccelAndGyro.h"
#include "LightProximityAndGesture.h"
#include "oled.h"

// D4 = GREEN START button (GPIO4). D16 = RED END / RETURN button (GPIO16).
// Both wired GND + INPUT_PULLUP: released HIGH, pressed LOW.
#if defined(D4)
constexpr int START_BUTTON_PIN = D4;
#else
constexpr int START_BUTTON_PIN = 4;
#endif
#if defined(D16)
constexpr int END_BUTTON_PIN = D16;
#else
constexpr int END_BUTTON_PIN = 16;
#endif
constexpr uint8_t STATUS_LED_PIN = 2;

constexpr unsigned long kSamplePeriodMs = 40;
constexpr unsigned long kOledUpdateMs = 200;
constexpr unsigned long kApdsPollMs = 80;
constexpr unsigned long kButtonDebounceMs = 40;
constexpr unsigned long kButtonActionHoldMs = 80;
constexpr unsigned long kEndHoldMs = kButtonActionHoldMs;
constexpr unsigned long kDockIgnoreMs = 100;
constexpr unsigned long kHoverDwellMs = 2000;
constexpr unsigned long kOcclusionLossResetMs = 400;

constexpr float kDefaultOcclusionEnterPct = 15.0f;
constexpr float kDefaultOcclusionExitPct = 8.0f;
constexpr bool USE_APDS_OCCLUSION_GATE = true;

constexpr size_t kCalibMaxSamples = 10;
constexpr size_t kCalibMinSamples = 3;
constexpr float kBaselineEmaAlpha = 0.992f;

constexpr float kStableGyroMax = 80.0f;
constexpr float kStableJerkMax = 800.0f;

// Course traversal defaults (used when scoring not calibrated from a reference trial)
constexpr float DEF_COURSE_GYRO_RMS_GOOD = 130.0f;
constexpr float DEF_COURSE_GYRO_RMS_BAD = 260.0f;
constexpr float DEF_COURSE_JERK_RMS_GOOD = 1700.0f;
constexpr float DEF_COURSE_JERK_RMS_BAD = 4200.0f;
constexpr float DEF_COURSE_SPIKE_RATE_GOOD = 5.5f;
constexpr float DEF_COURSE_SPIKE_RATE_BAD = 11.0f;
constexpr float DEF_HOVER_GYRO_RMS_GOOD = 90.0f;
constexpr float DEF_HOVER_GYRO_RMS_BAD = 180.0f;
constexpr float DEF_HOVER_JERK_RMS_GOOD = 900.0f;
constexpr float DEF_HOVER_JERK_RMS_BAD = 1800.0f;
constexpr float COURSE_GYRO_SPIKE_THRESH = 170.0f;
constexpr float COURSE_JERK_SPIKE_THRESH = 2300.0f;
constexpr float COURSE_PAUSE_GYRO_THRESH = 8.0f;
constexpr float COURSE_PAUSE_JERK_THRESH = 50.0f;
constexpr unsigned long COURSE_PAUSE_MIN_MS = 1500;
constexpr unsigned long COURSE_APPROACH_TIME_GOOD_MS = 16000;
constexpr unsigned long COURSE_APPROACH_TIME_BAD_MS = 40000;
constexpr float COURSE_WOBBLE_GYRO_THRESH = 140.0f;

// Hover phase
constexpr float HOVER_GYRO_SPIKE_THRESH = 120.0f;
constexpr float HOVER_JERK_SPIKE_THRESH = 1200.0f;
constexpr float kScoreCalEmaAlpha = 0.35f;
constexpr unsigned long kLivePrintMs = 1500;
constexpr uint8_t kRollWinSize = 25;
constexpr unsigned long HOVER_TIME_SLACK_MS = 5000;

// Axis / tilt
constexpr float TILT_GOOD_DEG = 12.0f;
constexpr float TILT_WARN_DEG = 25.0f;
constexpr float TILT_BAD_DEG = 40.0f;
constexpr float TILT_DYNAMIC_JERK_IGNORE = 2500.0f;
constexpr float kAccelLpfAlpha = 0.85f;
constexpr float kTiltBaselineEmaAlpha = 0.995f;

// Flow / timing (total trial)
constexpr unsigned long FLOW_PLATEAU_LO_MS = 25000;
constexpr unsigned long FLOW_PLATEAU_HI_MS = 35000;
constexpr unsigned long FLOW_FAST_LO_MS = 20000;
constexpr unsigned long FLOW_SLOW_HI_MS = 45000;
constexpr unsigned long FLOW_MIN_MS = 15000;
constexpr unsigned long FLOW_MAX_MS = 60000;

// Dock
constexpr unsigned long DOCK_TIME_GOOD_MS = 3000;
constexpr unsigned long DOCK_TIME_BAD_MS = 15000;
constexpr float DOCK_JERK_GOOD = 500.0f;
constexpr float DOCK_JERK_BAD = 3500.0f;
constexpr float DOCK_GYRO_GOOD = 50.0f;
constexpr float DOCK_GYRO_BAD = 250.0f;

constexpr bool STREAM_RAW_CSV_DEFAULT = false;

constexpr uint8_t kApdsAddr = APDS9960_I2C_ADDRESS;

enum class TrialState : uint8_t {
  Idle,
  Approach,
  Hover,
  Dock,
  Complete,
};

namespace {

LightProximityAndGesture apds;
AccelAndGyro imu;
oLed display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire);

bool g_apds_ok = false;
bool g_imu_ok = false;
bool g_oled_ok = false;
bool g_stream_raw_csv = STREAM_RAW_CSV_DEFAULT;

TrialState g_state = TrialState::Idle;
uint16_t g_trial_id = 0;
unsigned long g_sample_index = 0;
unsigned long g_next_sample_ms = 0;
unsigned long g_state_enter_ms = 0;
unsigned long g_last_oled_ms = 0;

uint16_t g_baseline_clear = 0;
bool g_baseline_valid = false;
bool g_apds_occlusion_latched = false;
unsigned long g_last_apds_poll_ms = 0;
uint32_t g_apds_read_fail_count = 0;
uint32_t g_apds_consecutive_fail_count = 0;
bool g_apds_warn_emitted = false;

float g_occlusion_enter_pct = kDefaultOcclusionEnterPct;
float g_occlusion_exit_pct = kDefaultOcclusionExitPct;

float g_calib_open[kCalibMaxSamples];
float g_calib_covered[kCalibMaxSamples];
uint8_t g_calib_open_count = 0;
uint8_t g_calib_covered_count = 0;

bool g_start_action_consumed = false;
bool g_end_action_consumed = false;
bool g_last_is_stable = false;

uint32_t g_hover_ms = 0;
unsigned long g_last_hover_accum_ms = 0;
unsigned long g_occlusion_lost_ms = 0;

float g_prev_acc_mag = 0.0f;
unsigned long g_prev_motion_ms = 0;

float g_baseline_ax = 0.0f;
float g_baseline_ay = 0.0f;
float g_baseline_az = 1.0f;
bool g_tilt_baseline_valid = false;
float g_lpf_ax = 0.0f;
float g_lpf_ay = 0.0f;
float g_lpf_az = 0.0f;
bool g_lpf_accel_init = false;
float g_tilt_deg_current = 0.0f;

unsigned long g_course_pause_start_ms = 0;
bool g_course_in_pause = false;
bool g_course_prev_wobble_high = false;

char g_last_feedback[24] = "";
unsigned long g_last_approach_ms = 0;
unsigned long g_last_hover_phase_ms = 0;
unsigned long g_last_dock_phase_ms = 0;

bool g_score_calibrated = false;
float g_cal_course_gyro_rms = 0.0f;
float g_cal_course_jerk_rms = 0.0f;
float g_cal_course_spike_rate = 0.0f;
float g_cal_hover_gyro_rms = 0.0f;
float g_cal_hover_jerk_rms = 0.0f;
float g_cal_dock_jerk_peak = 0.0f;

float g_roll_gyro[kRollWinSize];
float g_roll_jerk[kRollWinSize];
uint8_t g_roll_spike[kRollWinSize];
float g_roll_tilt[kRollWinSize];
uint8_t g_roll_idx = 0;
uint8_t g_roll_count = 0;
unsigned long g_last_live_print_ms = 0;
char g_current_live_issue[32] = "Smooth";

uint8_t g_gain_index = 1;
const uint8_t kGainCodes[] = {AGAIN_1X, AGAIN_4X, AGAIN_16X, AGAIN_64X};

constexpr size_t kEventQueueSize = 4;
constexpr size_t kEventMaxLen = 28;

char g_event_queue[kEventQueueSize][kEventMaxLen];
uint8_t g_event_head = 0;
uint8_t g_event_tail = 0;
uint8_t g_event_count = 0;
char g_last_csv_event[kEventMaxLen] = "";

constexpr uint32_t kApdsFailWarnThreshold = 10;

struct TrialMetrics {
  uint16_t trial_id = 0;
  unsigned long trial_start_ms = 0;
  unsigned long hover_enter_ms = 0;
  unsigned long hover_complete_ms = 0;
  unsigned long dock_complete_ms = 0;
  unsigned long approach_time_ms = 0;
  unsigned long hover_time_ms = 0;
  unsigned long dock_time_ms = 0;
  unsigned long total_trial_time_ms = 0;
  bool got_trial_start = false;
  bool got_hover_enter = false;
  bool got_hover_complete = false;
  bool got_dock_complete = false;

  uint32_t course_sample_count = 0;
  float course_gyro_sum = 0.0f;
  float course_gyro_sumsq = 0.0f;
  float course_gyro_max = 0.0f;
  float course_jerk_sum = 0.0f;
  float course_jerk_sumsq = 0.0f;
  float course_jerk_max = 0.0f;
  uint32_t course_gyro_spike_count = 0;
  uint32_t course_jerk_spike_count = 0;
  unsigned long course_pause_time_ms = 0;
  uint32_t course_wobble_events = 0;
  float course_tilt_sumsq = 0.0f;
  uint32_t course_tilt_samples = 0;

  uint32_t hover_reset_count = 0;
  uint32_t occlusion_loss_count = 0;
  uint32_t hover_total_samples = 0;
  uint32_t hover_stable_samples = 0;
  uint32_t hover_unstable_sample_count = 0;
  uint32_t hover_occluded_samples = 0;
  float occlusion_pct_sum_hover = 0.0f;
  float hover_gyro_sum = 0.0f;
  float hover_gyro_sumsq = 0.0f;
  float hover_jerk_sum = 0.0f;
  float hover_jerk_sumsq = 0.0f;
  uint32_t hover_gyro_spike_count = 0;
  uint32_t hover_jerk_spike_count = 0;
  float hover_tilt_sumsq = 0.0f;
  uint32_t hover_tilt_samples = 0;

  float tilt_deg_max = 0.0f;
  unsigned long tilt_over_limit_time_ms = 0;
  uint32_t tilt_over_limit_count = 0;
  float tilt_deg_rms_course = 0.0f;
  float tilt_deg_rms_hover = 0.0f;

  float dock_jerk_peak_recent = 0.0f;
  float dock_gyro_peak_recent = 0.0f;

  int course_score = 0;
  int hover_score = 0;
  int axis_score = 0;
  int flow_score = 0;
  int target_score = 0;
  int dock_score = 0;
  int total_score = 0;

  int pen_course = 0;
  int pen_hover = 0;
  int pen_axis = 0;
  int pen_flow = 0;
  int pen_target = 0;
  int pen_dock = 0;

  char feedback[24] = "";
};

TrialMetrics g_metrics;
TrialMetrics g_last_completed_metrics;
bool g_has_last_completed_metrics = false;
char g_previous_phase_name[12] = "";
int g_previous_phase_score = 0;
int g_last_completed_trial_score = 0;

struct DebouncedButton {
  uint8_t pin = 255;
  bool raw_pressed = false;
  bool stable_pressed = false;
  bool prev_stable_pressed = false;
  bool pressed_edge = false;
  bool released_edge = false;
  bool last_raw = false;
  unsigned long stable_pressed_since_ms = 0;
  unsigned long last_raw_change_ms = 0;
  unsigned long pressed_ms = 0;
  unsigned long debounce_ms = kButtonDebounceMs;
};

DebouncedButton startButton;
DebouncedButton endButton;

bool g_dock_complete_consumed = false;
unsigned long g_dock_enter_ms = 0;

int clampScore(int value, int min_val, int max_val) {
  if (value < min_val) {
    return min_val;
  }
  if (value > max_val) {
    return max_val;
  }
  return value;
}

void clearEventQueue() {
  g_event_head = 0;
  g_event_tail = 0;
  g_event_count = 0;
  for (size_t i = 0; i < kEventQueueSize; ++i) {
    g_event_queue[i][0] = '\0';
  }
  g_last_csv_event[0] = '\0';
}

bool pushEvent(const char *ev) {
  if (ev == nullptr || ev[0] == '\0') {
    return false;
  }
  if (g_event_count >= kEventQueueSize) {
    g_event_head = static_cast<uint8_t>((g_event_head + 1) % kEventQueueSize);
    g_event_count--;
  }
  strncpy(g_event_queue[g_event_tail], ev, kEventMaxLen - 1);
  g_event_queue[g_event_tail][kEventMaxLen - 1] = '\0';
  g_event_tail = static_cast<uint8_t>((g_event_tail + 1) % kEventQueueSize);
  g_event_count++;
  return true;
}

const char *stateName(TrialState s) {
  switch (s) {
    case TrialState::Idle:
      return "IDLE";
    case TrialState::Approach:
      return "APPROACH";
    case TrialState::Hover:
      return "HOVER";
    case TrialState::Dock:
      return "DOCK";
    case TrialState::Complete:
      return "COMPLETE";
  }
  return "IDLE";
}

void resetTrialMetrics() {
  g_metrics = TrialMetrics{};
  g_metrics.trial_id = g_trial_id;
}

float effCourseGyroRmsGood() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_course_gyro_rms * 1.15f, 80.0f);
  }
  return DEF_COURSE_GYRO_RMS_GOOD;
}

float effCourseGyroRmsBad() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_course_gyro_rms * 2.2f, effCourseGyroRmsGood() + 40.0f);
  }
  return DEF_COURSE_GYRO_RMS_BAD;
}

float effCourseJerkRmsGood() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_course_jerk_rms * 1.15f, 600.0f);
  }
  return DEF_COURSE_JERK_RMS_GOOD;
}

float effCourseJerkRmsBad() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_course_jerk_rms * 2.3f, effCourseJerkRmsGood() + 800.0f);
  }
  return DEF_COURSE_JERK_RMS_BAD;
}

float effCourseSpikeRateGood() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_course_spike_rate * 1.25f, 2.0f);
  }
  return DEF_COURSE_SPIKE_RATE_GOOD;
}

float effCourseSpikeRateBad() {
  if (g_score_calibrated) {
    const float scaled = g_cal_course_spike_rate * 2.5f;
    const float offset = g_cal_course_spike_rate + 2.0f;
    return fmaxf(scaled, fmaxf(offset, effCourseSpikeRateGood() + 2.0f));
  }
  return DEF_COURSE_SPIKE_RATE_BAD;
}

float effHoverGyroRmsGood() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_hover_gyro_rms * 1.15f, 50.0f);
  }
  return DEF_HOVER_GYRO_RMS_GOOD;
}

float effHoverGyroRmsBad() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_hover_gyro_rms * 2.2f, effHoverGyroRmsGood() + 30.0f);
  }
  return DEF_HOVER_GYRO_RMS_BAD;
}

float effHoverJerkRmsGood() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_hover_jerk_rms * 1.15f, 400.0f);
  }
  return DEF_HOVER_JERK_RMS_GOOD;
}

float effHoverJerkRmsBad() {
  if (g_score_calibrated) {
    return fmaxf(g_cal_hover_jerk_rms * 2.3f, effHoverJerkRmsGood() + 500.0f);
  }
  return DEF_HOVER_JERK_RMS_BAD;
}

float effDockJerkBad() {
  if (g_score_calibrated && g_cal_dock_jerk_peak > 0.0f) {
    return fmaxf(g_cal_dock_jerk_peak * 2.5f, 4500.0f);
  }
  return 5500.0f;
}

void clearScoreCalibration() {
  g_score_calibrated = false;
  Serial.println(F("CAL_CLEAR: scoring thresholds reset to defaults"));
}

void pushRollingSample(float gyro_mag, float jerk_proxy, bool is_spike, float tilt_deg) {
  g_roll_gyro[g_roll_idx] = gyro_mag;
  g_roll_jerk[g_roll_idx] = jerk_proxy;
  g_roll_spike[g_roll_idx] = is_spike ? 1 : 0;
  g_roll_tilt[g_roll_idx] = tilt_deg;
  g_roll_idx = static_cast<uint8_t>((g_roll_idx + 1) % kRollWinSize);
  if (g_roll_count < kRollWinSize) {
    g_roll_count++;
  }
}

void rollingWindowStats(float *gyro_rms, float *jerk_rms, float *spike_rate, float *tilt_rms) {
  if (gyro_rms) {
    *gyro_rms = 0.0f;
  }
  if (jerk_rms) {
    *jerk_rms = 0.0f;
  }
  if (spike_rate) {
    *spike_rate = 0.0f;
  }
  if (tilt_rms) {
    *tilt_rms = 0.0f;
  }
  if (g_roll_count == 0) {
    return;
  }
  float g_sum = 0.0f;
  float g_sq = 0.0f;
  float j_sum = 0.0f;
  float j_sq = 0.0f;
  float t_sq = 0.0f;
  uint32_t spikes = 0;
  for (uint8_t i = 0; i < g_roll_count; ++i) {
    const float g = g_roll_gyro[i];
    const float j = g_roll_jerk[i];
    g_sum += g;
    g_sq += g * g;
    j_sum += j;
    j_sq += j * j;
    t_sq += g_roll_tilt[i] * g_roll_tilt[i];
    spikes += g_roll_spike[i];
  }
  const float n = static_cast<float>(g_roll_count);
  if (gyro_rms) {
    *gyro_rms = sqrtf(g_sq / n);
  }
  if (jerk_rms) {
    *jerk_rms = sqrtf(j_sq / n);
  }
  if (tilt_rms) {
    *tilt_rms = sqrtf(t_sq / n);
  }
  if (spike_rate) {
    const float win_sec = n * static_cast<float>(kSamplePeriodMs) / 1000.0f;
    *spike_rate = win_sec > 0.05f ? static_cast<float>(spikes) / win_sec : 0.0f;
  }
}

float computeRms(float sumsq, uint32_t count) {
  if (count == 0) {
    return 0.0f;
  }
  return sqrtf(sumsq / static_cast<float>(count));
}

float penaltyRamp(float val, float good, float bad, float max_pen) {
  if (val <= good) {
    return 0.0f;
  }
  if (val >= bad) {
    return max_pen;
  }
  return max_pen * (val - good) / (bad - good);
}

void computeDerivedRms(TrialMetrics *m) {
  if (m == nullptr) {
    return;
  }
  m->tilt_deg_rms_course = computeRms(m->course_tilt_sumsq, m->course_tilt_samples);
  m->tilt_deg_rms_hover = computeRms(m->hover_tilt_sumsq, m->hover_tilt_samples);
}

void computePhaseTimes(TrialMetrics *m) {
  if (m == nullptr) {
    return;
  }
  m->approach_time_ms = 0;
  m->hover_time_ms = 0;
  m->dock_time_ms = 0;
  if (m->got_hover_enter && m->trial_start_ms > 0) {
    m->approach_time_ms = m->hover_enter_ms - m->trial_start_ms;
  }
  if (m->got_hover_complete && m->got_hover_enter) {
    m->hover_time_ms = m->hover_complete_ms - m->hover_enter_ms;
  }
  if (m->got_dock_complete && m->got_hover_complete) {
    m->dock_time_ms = m->dock_complete_ms - m->hover_complete_ms;
  }
  if (m->got_dock_complete && m->trial_start_ms > 0) {
    m->total_trial_time_ms = m->dock_complete_ms - m->trial_start_ms;
  }
}

void scoreCourseTraversal(TrialMetrics *m, int *pen_out) {
  int s = 35;
  int pen = 0;
  const float gyro_rms = computeRms(m->course_gyro_sumsq, m->course_sample_count);
  const float jerk_rms = computeRms(m->course_jerk_sumsq, m->course_sample_count);

  const int gyro_rms_pen = static_cast<int>(
      penaltyRamp(gyro_rms, effCourseGyroRmsGood(), effCourseGyroRmsBad(), 7.0f));
  const int jerk_rms_pen = static_cast<int>(
      penaltyRamp(jerk_rms, effCourseJerkRmsGood(), effCourseJerkRmsBad(), 7.0f));
  pen += gyro_rms_pen + jerk_rms_pen;
  s -= gyro_rms_pen + jerk_rms_pen;

  float course_sec = 0.0f;
  if (m->approach_time_ms > 0) {
    course_sec = static_cast<float>(m->approach_time_ms) / 1000.0f;
  } else if (m->course_sample_count > 0) {
    course_sec = static_cast<float>(m->course_sample_count) * static_cast<float>(kSamplePeriodMs) /
                 1000.0f;
  }
  if (course_sec > 0.1f) {
    const float spike_rate = static_cast<float>(m->course_gyro_spike_count + m->course_jerk_spike_count) /
                             course_sec;
    const int spike_pen = static_cast<int>(
        penaltyRamp(spike_rate, effCourseSpikeRateGood(), effCourseSpikeRateBad(), 6.0f));
    pen += spike_pen;
    s -= spike_pen;
  }

  const int pause_pen = static_cast<int>(
      penaltyRamp(static_cast<float>(m->course_pause_time_ms),
                  static_cast<float>(COURSE_PAUSE_MIN_MS), 10000.0f, 4.0f));
  pen += pause_pen;
  s -= pause_pen;

  if (m->approach_time_ms > COURSE_APPROACH_TIME_BAD_MS) {
    pen += 4;
    s -= 4;
  } else if (m->approach_time_ms > COURSE_APPROACH_TIME_GOOD_MS) {
    const float t = static_cast<float>(m->approach_time_ms - COURSE_APPROACH_TIME_GOOD_MS) /
                    static_cast<float>(COURSE_APPROACH_TIME_BAD_MS - COURSE_APPROACH_TIME_GOOD_MS);
    const int time_pen = static_cast<int>(t * 4.0f);
    pen += time_pen;
    s -= time_pen;
  }

  m->course_score = clampScore(s, 0, 35);
  if (pen_out) {
    *pen_out = pen;
  }
}

void scoreHoverPrecision(TrialMetrics *m, int *pen_out) {
  int s = 30;
  int pen = 0;

  const int reset_pen = static_cast<int>(m->hover_reset_count) * 6;
  const int reset_cap = reset_pen > 18 ? 18 : reset_pen;
  pen += reset_cap;
  s -= reset_cap;

  if (m->hover_total_samples > 0) {
    const float unstable_frac =
        static_cast<float>(m->hover_unstable_sample_count) /
        static_cast<float>(m->hover_total_samples);
    float unstable_max = 4.0f;
    float unstable_bad = 0.70f;
    if (m->got_hover_complete && m->hover_reset_count == 0) {
      unstable_max = 2.0f;
      unstable_bad = 0.80f;
    }
    const int unstable_pen =
        static_cast<int>(penaltyRamp(unstable_frac, 0.30f, unstable_bad, unstable_max));
    pen += unstable_pen;
    s -= unstable_pen;
  }

  const float hover_gyro_rms = computeRms(m->hover_gyro_sumsq, m->hover_total_samples);
  const float hover_jerk_rms = computeRms(m->hover_jerk_sumsq, m->hover_total_samples);
  const int gyro_pen = static_cast<int>(
      penaltyRamp(hover_gyro_rms, effHoverGyroRmsGood(), effHoverGyroRmsBad(), 4.0f));
  const int jerk_pen = static_cast<int>(
      penaltyRamp(hover_jerk_rms, effHoverJerkRmsGood(), effHoverJerkRmsBad(), 4.0f));
  pen += gyro_pen + jerk_pen;
  s -= gyro_pen + jerk_pen;

  if (m->hover_time_ms > kHoverDwellMs + HOVER_TIME_SLACK_MS) {
    const unsigned long extra = m->hover_time_ms - kHoverDwellMs - HOVER_TIME_SLACK_MS;
    const int time_pen = static_cast<int>(penaltyRamp(static_cast<float>(extra), 0.0f, 12000.0f, 3.0f));
    pen += time_pen;
    s -= time_pen;
  }

  m->hover_score = clampScore(s, 0, 30);

  if (m->got_hover_complete && m->hover_reset_count == 0) {
    float occ_frac = 1.0f;
    if (m->hover_total_samples > 0) {
      occ_frac = static_cast<float>(m->hover_occluded_samples) /
                 static_cast<float>(m->hover_total_samples);
    }
    if (occ_frac >= 0.95f) {
      m->hover_score = clampScore(m->hover_score > 24 ? m->hover_score : 24, 0, 30);
    }
    if (m->hover_time_ms > 0 && m->hover_time_ms <= 4000) {
      m->hover_score = clampScore(m->hover_score > 25 ? m->hover_score : 25, 0, 30);
    }
  }

  if (pen_out) {
    *pen_out = 30 - m->hover_score;
  }
  m->pen_hover = 30 - m->hover_score;
}

void scoreAxisDiscipline(TrialMetrics *m, int *pen_out) {
  int s = 15;
  int pen = 0;

  const float tilt_rms =
      (m->tilt_deg_rms_hover > 0.0f)
          ? (m->tilt_deg_rms_hover * 0.6f + m->tilt_deg_rms_course * 0.4f)
          : m->tilt_deg_rms_course;
  const int rms_pen = static_cast<int>(penaltyRamp(tilt_rms, TILT_GOOD_DEG, TILT_BAD_DEG, 6.0f));
  pen += rms_pen;
  s -= rms_pen;

  const int warn_time_pen = static_cast<int>(
      penaltyRamp(static_cast<float>(m->tilt_over_limit_time_ms), 0.0f, 4000.0f, 5.0f));
  pen += warn_time_pen;
  s -= warn_time_pen;

  const int max_pen = static_cast<int>(penaltyRamp(m->tilt_deg_max, TILT_WARN_DEG, TILT_BAD_DEG + 15.0f, 4.0f));
  pen += max_pen;
  s -= max_pen;

  m->axis_score = clampScore(s, 0, 15);
  if (pen_out) {
    *pen_out = pen;
  }
}

int scoreFlowTiming(unsigned long total_ms) {
  if (total_ms >= FLOW_PLATEAU_LO_MS && total_ms <= FLOW_PLATEAU_HI_MS) {
    return 10;
  }
  if (total_ms >= FLOW_FAST_LO_MS && total_ms < FLOW_PLATEAU_LO_MS) {
    const float t = static_cast<float>(FLOW_PLATEAU_LO_MS - total_ms) /
                    static_cast<float>(FLOW_PLATEAU_LO_MS - FLOW_FAST_LO_MS);
    return clampScore(static_cast<int>(7.0f + t * 3.0f), 0, 10);
  }
  if (total_ms > FLOW_PLATEAU_HI_MS && total_ms <= FLOW_SLOW_HI_MS) {
    const float t = static_cast<float>(total_ms - FLOW_PLATEAU_HI_MS) /
                    static_cast<float>(FLOW_SLOW_HI_MS - FLOW_PLATEAU_HI_MS);
    return clampScore(static_cast<int>(10.0f - t * 2.0f), 0, 10);
  }
  if (total_ms >= FLOW_MIN_MS && total_ms < FLOW_FAST_LO_MS) {
    const float t = static_cast<float>(FLOW_FAST_LO_MS - total_ms) /
                    static_cast<float>(FLOW_FAST_LO_MS - FLOW_MIN_MS);
    return clampScore(static_cast<int>(5.0f + t * 2.0f), 0, 10);
  }
  if (total_ms > FLOW_SLOW_HI_MS && total_ms <= FLOW_MAX_MS) {
    const float t = static_cast<float>(total_ms - FLOW_SLOW_HI_MS) /
                    static_cast<float>(FLOW_MAX_MS - FLOW_SLOW_HI_MS);
    return clampScore(static_cast<int>(8.0f - t * 4.0f), 0, 10);
  }
  if (total_ms < FLOW_MIN_MS) {
    return 4;
  }
  if (total_ms > FLOW_MAX_MS) {
    const float t = static_cast<float>(total_ms - FLOW_MAX_MS) / 30000.0f;
    return clampScore(static_cast<int>(4.0f - t * 4.0f), 0, 10);
  }
  return 0;
}

void scoreTargetApds(TrialMetrics *m, int *pen_out) {
  int s = 5;
  int pen = 0;

  float hover_occluded_fraction = 1.0f;
  if (m->hover_total_samples > 0) {
    hover_occluded_fraction = static_cast<float>(m->hover_occluded_samples) /
                              static_cast<float>(m->hover_total_samples);
  }

  if (m->got_hover_complete && m->hover_reset_count == 0 && hover_occluded_fraction >= 0.95f &&
      m->occlusion_loss_count == 0) {
    m->target_score = 5;
    if (pen_out) {
      *pen_out = 0;
    }
    return;
  }

  if (hover_occluded_fraction < 0.85f) {
    pen += 2;
    s -= 2;
  }
  if (m->occlusion_loss_count > 0) {
    pen += 2;
    s -= 2;
  }

  m->target_score = clampScore(s, 0, 5);
  if (pen_out) {
    *pen_out = pen;
  }
}

void scoreDockQuality(TrialMetrics *m, int *pen_out) {
  int s = 5;
  int pen = 0;

  if (m->dock_time_ms > DOCK_TIME_BAD_MS) {
    pen += 2;
    s -= 2;
  } else if (m->dock_time_ms > DOCK_TIME_GOOD_MS) {
    const int time_pen = static_cast<int>(penaltyRamp(static_cast<float>(m->dock_time_ms),
                                                      static_cast<float>(DOCK_TIME_GOOD_MS),
                                                      static_cast<float>(DOCK_TIME_BAD_MS), 2.0f));
    pen += time_pen;
    s -= time_pen;
  }

  const int jerk_pen = static_cast<int>(
      penaltyRamp(m->dock_jerk_peak_recent, DOCK_JERK_GOOD, effDockJerkBad(), 1.0f));
  pen += jerk_pen;
  s -= jerk_pen;

  const int gyro_pen = static_cast<int>(
      penaltyRamp(m->dock_gyro_peak_recent, DOCK_GYRO_GOOD, DOCK_GYRO_BAD, 1.0f));
  pen += gyro_pen;
  s -= gyro_pen;

  m->dock_score = clampScore(s, 0, 5);
  if (pen_out) {
    *pen_out = pen;
  }
}

void chooseFeedbackLabel(TrialMetrics *m) {
  if (m == nullptr) {
    return;
  }
  const char *label = "Good control";

  if (!m->got_dock_complete) {
    label = "Incomplete";
  } else if (m->hover_reset_count > 0) {
    label = "Hover unstable";
  } else if (m->target_score < 3 || m->occlusion_loss_count > 0) {
    label = "Lost target";
  } else if (m->axis_score < 10) {
    label = "Handle off-axis";
  } else if (m->course_score < 22) {
    const float jerk_rms = computeRms(m->course_jerk_sumsq, m->course_sample_count);
    float course_sec = static_cast<float>(m->approach_time_ms) / 1000.0f;
    const float spike_rate =
        course_sec > 0.1f
            ? static_cast<float>(m->course_gyro_spike_count + m->course_jerk_spike_count) /
                  course_sec
            : 0.0f;
    if (jerk_rms > effCourseJerkRmsBad() * 0.9f || spike_rate > effCourseSpikeRateBad() * 0.9f) {
      label = "Course too jerky";
    } else {
      label = "Too much rotation";
    }
  } else if (m->flow_score < 7 && m->total_trial_time_ms < FLOW_PLATEAU_LO_MS) {
    label = (m->course_score >= 25) ? "Fast but controlled" : "Too fast";
  } else if (m->flow_score < 7 && m->total_trial_time_ms > FLOW_SLOW_HI_MS) {
    label = "Too slow";
  } else if (m->dock_score <= 2 && m->total_score > 70) {
    label = "Dock too harsh";
  } else if (m->total_score > 85) {
    label = "Great control";
  } else if (m->course_score >= 28 && m->hover_score < 20) {
    label = "Improve hover";
  }

  strncpy(m->feedback, label, sizeof(m->feedback) - 1);
  m->feedback[sizeof(m->feedback) - 1] = '\0';
  strncpy(g_last_feedback, m->feedback, sizeof(m->feedback) - 1);
  g_last_feedback[sizeof(g_last_feedback) - 1] = '\0';
}

void computeFinalComponentScores(TrialMetrics *m) {
  if (m == nullptr || !m->got_dock_complete) {
    return;
  }
  computeDerivedRms(m);
  computePhaseTimes(m);

  scoreCourseTraversal(m, &m->pen_course);
  scoreHoverPrecision(m, &m->pen_hover);
  scoreAxisDiscipline(m, &m->pen_axis);
  m->flow_score = scoreFlowTiming(m->total_trial_time_ms);
  m->pen_flow = 10 - m->flow_score;
  scoreTargetApds(m, &m->pen_target);
  scoreDockQuality(m, &m->pen_dock);

  m->total_score =
      clampScore(m->course_score + m->hover_score + m->axis_score + m->flow_score +
                     m->target_score + m->dock_score,
                 0, 100);
  chooseFeedbackLabel(m);

  g_last_approach_ms = m->approach_time_ms;
  g_last_hover_phase_ms = m->hover_time_ms;
  g_last_dock_phase_ms = m->dock_time_ms;
}

void computeActiveComponentScores(TrialMetrics *m) {
  if (m == nullptr) {
    return;
  }
  computeDerivedRms(m);
  if (m->got_hover_enter && m->trial_start_ms > 0 && m->approach_time_ms == 0) {
    m->approach_time_ms = millis() - m->trial_start_ms;
  }
  scoreCourseTraversal(m, &m->pen_course);
  scoreHoverPrecision(m, &m->pen_hover);
  scoreAxisDiscipline(m, &m->pen_axis);
  const unsigned long total_ms =
      m->trial_start_ms > 0 ? millis() - m->trial_start_ms : 0;
  m->flow_score = scoreFlowTiming(total_ms);
  m->pen_flow = 10 - m->flow_score;
  scoreTargetApds(m, &m->pen_target);
  scoreDockQuality(m, &m->pen_dock);
  m->total_score =
      clampScore(m->course_score + m->hover_score + m->axis_score + m->flow_score +
                     m->target_score + m->dock_score,
                 0, 100);
}

int computeActiveScoreEstimate() {
  TrialMetrics est = g_metrics;
  computeActiveComponentScores(&est);
  return est.total_score;
}

void applyScoreCalibrationFromLastTrial() {
  if (!g_has_last_completed_metrics) {
    Serial.println(F("CAL_SET_ERR: complete a trial first, then press c"));
    return;
  }
  const TrialMetrics &m = g_last_completed_metrics;
  const float course_gyro = computeRms(m.course_gyro_sumsq, m.course_sample_count);
  const float course_jerk = computeRms(m.course_jerk_sumsq, m.course_sample_count);
  float course_sec = 0.0f;
  if (m.approach_time_ms > 0) {
    course_sec = static_cast<float>(m.approach_time_ms) / 1000.0f;
  }
  const float course_spike =
      course_sec > 0.1f
          ? static_cast<float>(m.course_gyro_spike_count + m.course_jerk_spike_count) / course_sec
          : 0.0f;
  const float hover_gyro = computeRms(m.hover_gyro_sumsq, m.hover_total_samples);
  const float hover_jerk = computeRms(m.hover_jerk_sumsq, m.hover_total_samples);

  if (!g_score_calibrated) {
    g_cal_course_gyro_rms = course_gyro;
    g_cal_course_jerk_rms = course_jerk;
    g_cal_course_spike_rate = course_spike;
    g_cal_hover_gyro_rms = hover_gyro;
    g_cal_hover_jerk_rms = hover_jerk;
    g_cal_dock_jerk_peak = m.dock_jerk_peak_recent;
    g_score_calibrated = true;
  } else {
    g_cal_course_gyro_rms =
        kScoreCalEmaAlpha * g_cal_course_gyro_rms + (1.0f - kScoreCalEmaAlpha) * course_gyro;
    g_cal_course_jerk_rms =
        kScoreCalEmaAlpha * g_cal_course_jerk_rms + (1.0f - kScoreCalEmaAlpha) * course_jerk;
    g_cal_course_spike_rate =
        kScoreCalEmaAlpha * g_cal_course_spike_rate + (1.0f - kScoreCalEmaAlpha) * course_spike;
    g_cal_hover_gyro_rms =
        kScoreCalEmaAlpha * g_cal_hover_gyro_rms + (1.0f - kScoreCalEmaAlpha) * hover_gyro;
    g_cal_hover_jerk_rms =
        kScoreCalEmaAlpha * g_cal_hover_jerk_rms + (1.0f - kScoreCalEmaAlpha) * hover_jerk;
    g_cal_dock_jerk_peak =
        kScoreCalEmaAlpha * g_cal_dock_jerk_peak + (1.0f - kScoreCalEmaAlpha) * m.dock_jerk_peak_recent;
  }

  Serial.print(F("CAL_SET,course_gyro_rms="));
  Serial.print(g_cal_course_gyro_rms, 1);
  Serial.print(F(",course_jerk_rms="));
  Serial.print(g_cal_course_jerk_rms, 1);
  Serial.print(F(",course_spike_rate="));
  Serial.print(g_cal_course_spike_rate, 2);
  Serial.print(F(",hover_gyro_rms="));
  Serial.print(g_cal_hover_gyro_rms, 1);
  Serial.print(F(",hover_jerk_rms="));
  Serial.print(g_cal_hover_jerk_rms, 1);
  Serial.print(F(",dock_jerk_peak="));
  Serial.println(g_cal_dock_jerk_peak, 0);
}

int scoreForSerialOutput() {
  if (g_metrics.got_dock_complete) {
    return g_metrics.total_score;
  }
  if (g_last_completed_trial_score > 0 &&
      (g_state == TrialState::Complete || g_state == TrialState::Idle)) {
    return g_last_completed_trial_score;
  }
  if (g_metrics.got_trial_start && !g_metrics.got_dock_complete) {
    return computeActiveScoreEstimate();
  }
  return 0;
}

void computeFinalScore() {
  computeFinalComponentScores(&g_metrics);
  g_last_completed_trial_score = g_metrics.total_score;
  g_last_completed_metrics = g_metrics;
  g_has_last_completed_metrics = true;
}

void printStateEventLine(unsigned long t_ms, const char *event) {
  Serial.print(F("EVENT,trial="));
  Serial.print(g_trial_id);
  Serial.print(F(",t_ms="));
  Serial.print(t_ms);
  Serial.print(F(",state="));
  Serial.print(stateName(g_state));
  Serial.print(F(",event="));
  Serial.print(event);
  Serial.print(F(",score="));
  Serial.println(scoreForSerialOutput());
}

void printScoreSummary() {
  if (!g_metrics.got_dock_complete) {
    return;
  }
  const float course_gyro_rms =
      computeRms(g_metrics.course_gyro_sumsq, g_metrics.course_sample_count);
  const float course_jerk_rms =
      computeRms(g_metrics.course_jerk_sumsq, g_metrics.course_sample_count);
  float course_sec = 0.0f;
  if (g_metrics.approach_time_ms > 0) {
    course_sec = static_cast<float>(g_metrics.approach_time_ms) / 1000.0f;
  }
  const float course_spike_rate =
      course_sec > 0.1f
          ? static_cast<float>(g_metrics.course_gyro_spike_count + g_metrics.course_jerk_spike_count) /
                course_sec
          : 0.0f;
  const float tilt_rms = (g_metrics.tilt_deg_rms_hover > 0.0f)
                             ? (g_metrics.tilt_deg_rms_hover * 0.6f +
                                g_metrics.tilt_deg_rms_course * 0.4f)
                             : g_metrics.tilt_deg_rms_course;
  float hover_stable_pct = 0.0f;
  float hover_occluded_pct = 0.0f;
  if (g_metrics.hover_total_samples > 0) {
    hover_stable_pct = 100.0f * static_cast<float>(g_metrics.hover_stable_samples) /
                       static_cast<float>(g_metrics.hover_total_samples);
    hover_occluded_pct = 100.0f * static_cast<float>(g_metrics.hover_occluded_samples) /
                         static_cast<float>(g_metrics.hover_total_samples);
  }

  Serial.print(F("FINAL_SCORE,trial="));
  Serial.print(g_metrics.trial_id);
  Serial.print(F(",total="));
  Serial.print(g_metrics.total_score);
  Serial.print(F(",course="));
  Serial.print(g_metrics.course_score);
  Serial.print(F(",hover="));
  Serial.print(g_metrics.hover_score);
  Serial.print(F(",axis="));
  Serial.print(g_metrics.axis_score);
  Serial.print(F(",flow="));
  Serial.print(g_metrics.flow_score);
  Serial.print(F(",target="));
  Serial.print(g_metrics.target_score);
  Serial.print(F(",dock="));
  Serial.print(g_metrics.dock_score);
  Serial.print(F(",feedback="));
  Serial.print(g_metrics.feedback);
  Serial.print(F(",total_ms="));
  Serial.print(g_metrics.total_trial_time_ms);
  Serial.print(F(",approach_ms="));
  Serial.print(g_metrics.approach_time_ms);
  Serial.print(F(",hover_ms="));
  Serial.print(g_metrics.hover_time_ms);
  Serial.print(F(",dock_ms="));
  Serial.print(g_metrics.dock_time_ms);
  Serial.print(F(",course_gyro_rms="));
  Serial.print(course_gyro_rms, 1);
  Serial.print(F(",course_jerk_rms="));
  Serial.print(course_jerk_rms, 1);
  Serial.print(F(",course_spike_rate="));
  Serial.print(course_spike_rate, 2);
  Serial.print(F(",tilt_rms="));
  Serial.print(tilt_rms, 1);
  Serial.print(F(",tilt_max="));
  Serial.print(g_metrics.tilt_deg_max, 1);
  Serial.print(F(",tilt_over_limit_ms="));
  Serial.print(g_metrics.tilt_over_limit_time_ms);
  Serial.print(F(",hover_stable_pct="));
  Serial.print(hover_stable_pct, 1);
  Serial.print(F(",hover_occluded_pct="));
  Serial.print(hover_occluded_pct, 1);
  Serial.print(F(",dock_jerk_peak="));
  Serial.print(g_metrics.dock_jerk_peak_recent, 0);
  Serial.print(F(",hover_resets="));
  Serial.print(g_metrics.hover_reset_count);
  Serial.print(F(",occlusion_losses="));
  Serial.println(g_metrics.occlusion_loss_count);
}

void printScoreBreakdown() {
  Serial.println(F("# --- score breakdown ---"));
  Serial.print(F("trial="));
  Serial.println(g_metrics.trial_id);
  if (!g_metrics.got_dock_complete) {
    Serial.println(F("status=INCOMPLETE (ACTIVE estimate during trial)"));
    computeActiveComponentScores(&g_metrics);
  } else {
    Serial.println(F("status=COMPLETE"));
    computeFinalComponentScores(&g_metrics);
  }
  Serial.print(F("total="));
  Serial.println(g_metrics.total_score);
  Serial.print(F("course="));
  Serial.print(g_metrics.course_score);
  Serial.println(F("/35"));
  Serial.print(F("hover="));
  Serial.print(g_metrics.hover_score);
  Serial.println(F("/30"));
  Serial.print(F("axis="));
  Serial.print(g_metrics.axis_score);
  Serial.println(F("/15"));
  Serial.print(F("flow="));
  Serial.print(g_metrics.flow_score);
  Serial.println(F("/10"));
  Serial.print(F("target="));
  Serial.print(g_metrics.target_score);
  Serial.println(F("/5"));
  Serial.print(F("dock="));
  Serial.print(g_metrics.dock_score);
  Serial.println(F("/5"));
  if (g_metrics.got_hover_enter) {
    Serial.print(F("approach_ms="));
    Serial.println(g_metrics.approach_time_ms > 0 ? g_metrics.approach_time_ms
                                                  : (millis() - g_metrics.trial_start_ms));
  }
  if (g_metrics.got_hover_complete) {
    Serial.print(F("hover_ms="));
    Serial.println(g_metrics.hover_time_ms);
  }
  if (g_metrics.got_dock_complete) {
    Serial.print(F("dock_ms="));
    Serial.println(g_metrics.dock_time_ms);
    Serial.print(F("total_ms="));
    Serial.println(g_metrics.total_trial_time_ms);
    Serial.print(F("feedback="));
    Serial.println(g_metrics.feedback);
  }
  const char *main_pen = "course";
  int max_pen = g_metrics.pen_course;
  if (g_metrics.pen_hover >= max_pen) {
    max_pen = g_metrics.pen_hover;
    main_pen = "hover";
  }
  if (g_metrics.pen_axis >= max_pen) {
    max_pen = g_metrics.pen_axis;
    main_pen = "axis";
  }
  if (g_metrics.pen_flow >= max_pen) {
    max_pen = g_metrics.pen_flow;
    main_pen = "flow";
  }
  if (g_metrics.pen_target >= max_pen) {
    max_pen = g_metrics.pen_target;
    main_pen = "target";
  }
  if (g_metrics.pen_dock >= max_pen) {
    main_pen = "dock";
  }
  Serial.print(F("main_penalty="));
  Serial.println(main_pen);
  const float course_gyro_rms =
      computeRms(g_metrics.course_gyro_sumsq, g_metrics.course_sample_count);
  const float course_jerk_rms =
      computeRms(g_metrics.course_jerk_sumsq, g_metrics.course_sample_count);
  float course_sec = 0.0f;
  if (g_metrics.approach_time_ms > 0) {
    course_sec = static_cast<float>(g_metrics.approach_time_ms) / 1000.0f;
  }
  const float course_spike_rate =
      course_sec > 0.1f
          ? static_cast<float>(g_metrics.course_gyro_spike_count + g_metrics.course_jerk_spike_count) /
                course_sec
          : 0.0f;
  Serial.print(F("course_gyro_rms="));
  Serial.println(course_gyro_rms, 1);
  Serial.print(F("course_jerk_rms="));
  Serial.println(course_jerk_rms, 1);
  Serial.print(F("course_spike_rate="));
  Serial.println(course_spike_rate, 2);
  if (g_metrics.hover_total_samples > 0) {
    const float hover_stable_pct =
        100.0f * static_cast<float>(g_metrics.hover_stable_samples) /
        static_cast<float>(g_metrics.hover_total_samples);
    Serial.print(F("hover_stable_pct="));
    Serial.println(hover_stable_pct, 1);
  }
  Serial.print(F("dock_jerk_peak="));
  Serial.println(g_metrics.dock_jerk_peak_recent, 0);
  Serial.print(F("calibration="));
  Serial.println(g_score_calibrated ? F("active") : F("default"));
  if (g_last_completed_trial_score > 0 && g_state == TrialState::Idle) {
    Serial.print(F("last_completed="));
    Serial.println(g_last_completed_trial_score);
  }
  Serial.println(F("# ---------------------"));
}

void printScoringThresholds() {
  Serial.println(F("# --- scoring thresholds ---"));
  Serial.print(F("calibration="));
  Serial.println(g_score_calibrated ? F("active") : F("default"));
  if (g_score_calibrated) {
    Serial.print(F("cal_course_gyro_rms="));
    Serial.println(g_cal_course_gyro_rms, 1);
    Serial.print(F("cal_course_jerk_rms="));
    Serial.println(g_cal_course_jerk_rms, 1);
    Serial.print(F("cal_course_spike_rate="));
    Serial.println(g_cal_course_spike_rate, 2);
  }
  Serial.print(F("course_gyro_rms good/bad="));
  Serial.print(effCourseGyroRmsGood(), 0);
  Serial.print(F("/"));
  Serial.println(effCourseGyroRmsBad(), 0);
  Serial.print(F("course_jerk_rms good/bad="));
  Serial.print(effCourseJerkRmsGood(), 0);
  Serial.print(F("/"));
  Serial.println(effCourseJerkRmsBad(), 0);
  Serial.print(F("course_spike_rate good/bad="));
  Serial.print(effCourseSpikeRateGood(), 1);
  Serial.print(F("/"));
  Serial.println(effCourseSpikeRateBad(), 1);
  Serial.print(F("hover_gyro_rms good/bad="));
  Serial.print(effHoverGyroRmsGood(), 0);
  Serial.print(F("/"));
  Serial.println(effHoverGyroRmsBad(), 0);
  Serial.print(F("tilt good/warn/bad="));
  Serial.print(TILT_GOOD_DEG, 0);
  Serial.print(F("/"));
  Serial.print(TILT_WARN_DEG, 0);
  Serial.print(F("/"));
  Serial.println(TILT_BAD_DEG, 0);
  Serial.print(F("flow_target_ms="));
  Serial.print(FLOW_PLATEAU_LO_MS);
  Serial.print(F("-"));
  Serial.println(FLOW_PLATEAU_HI_MS);
  Serial.print(F("apds_enter/exit="));
  Serial.print(g_occlusion_enter_pct, 1);
  Serial.print(F("/"));
  Serial.println(g_occlusion_exit_pct, 1);
  Serial.print(F("dock_jerk good/bad="));
  Serial.print(DOCK_JERK_GOOD, 0);
  Serial.print(F("/"));
  Serial.println(effDockJerkBad(), 0);
  Serial.println(F("# --------------------------"));
}

void applyEventToMetrics(const char *event, unsigned long t_ms) {
  if (event == nullptr) {
    return;
  }
  if (strcmp(event, "TRIAL_START") == 0) {
    g_metrics.got_trial_start = true;
    g_metrics.trial_start_ms = t_ms;
    g_course_in_pause = false;
    g_course_pause_start_ms = 0;
    g_course_prev_wobble_high = false;
  } else if (strcmp(event, "HOVER_ENTER") == 0) {
    g_metrics.got_hover_enter = true;
    g_metrics.hover_enter_ms = t_ms;
    if (g_metrics.trial_start_ms > 0) {
      g_metrics.approach_time_ms = t_ms - g_metrics.trial_start_ms;
    }
  } else if (strcmp(event, "HOVER_RESET") == 0) {
    g_metrics.hover_reset_count++;
    g_metrics.occlusion_loss_count++;
  } else if (strcmp(event, "HOVER_COMPLETE") == 0) {
    g_metrics.got_hover_complete = true;
    g_metrics.hover_complete_ms = t_ms;
    g_metrics.hover_time_ms = t_ms - g_metrics.hover_enter_ms;
    computeDerivedRms(&g_metrics);
    scoreHoverPrecision(&g_metrics, nullptr);
    strncpy(g_previous_phase_name, "Hover", sizeof(g_previous_phase_name) - 1);
    g_previous_phase_score = g_metrics.hover_score;
  } else if (strcmp(event, "DOCK_COMPLETE") == 0) {
    g_metrics.got_dock_complete = true;
    g_metrics.dock_complete_ms = t_ms;
    computeFinalScore();
    strncpy(g_previous_phase_name, "Trial", sizeof(g_previous_phase_name) - 1);
    g_previous_phase_score = g_metrics.total_score;
    g_last_completed_trial_score = g_metrics.total_score;
    printStateEventLine(t_ms, event);
    return;
  } else if (strcmp(event, "BASELINE_SET") == 0) {
    printStateEventLine(t_ms, event);
    return;
  } else if (strcmp(event, "RESET") == 0 || strcmp(event, "RETURN_TO_IDLE") == 0) {
    printStateEventLine(t_ms, event);
    return;
  } else if (strcmp(event, "GAIN_CHANGED") == 0) {
    printStateEventLine(t_ms, event);
    return;
  } else if (strcmp(event, "APDS_READ_WARN") == 0) {
    printStateEventLine(t_ms, event);
    return;
  }

  printStateEventLine(t_ms, event);
}

void processAllPendingEvents(unsigned long t_ms) {
  while (g_event_count > 0) {
    char ev[kEventMaxLen];
    strncpy(ev, g_event_queue[g_event_head], kEventMaxLen - 1);
    ev[kEventMaxLen - 1] = '\0';
    g_event_head = static_cast<uint8_t>((g_event_head + 1) % kEventQueueSize);
    g_event_count--;

    applyEventToMetrics(ev, t_ms);

    if (strcmp(ev, "DOCK_COMPLETE") == 0) {
      printScoreSummary();
    }

    strncpy(g_last_csv_event, ev, kEventMaxLen - 1);
    g_last_csv_event[kEventMaxLen - 1] = '\0';
  }
}

void normalizeAccel(float ax, float ay, float az, float *nx, float *ny, float *nz) {
  const float mag = sqrtf(ax * ax + ay * ay + az * az);
  if (mag < 0.1f) {
    *nx = 0.0f;
    *ny = 0.0f;
    *nz = 1.0f;
    return;
  }
  *nx = ax / mag;
  *ny = ay / mag;
  *nz = az / mag;
}

void updateAccelLpf(float ax, float ay, float az) {
  if (!g_lpf_accel_init) {
    g_lpf_ax = ax;
    g_lpf_ay = ay;
    g_lpf_az = az;
    g_lpf_accel_init = true;
    return;
  }
  g_lpf_ax = kAccelLpfAlpha * g_lpf_ax + (1.0f - kAccelLpfAlpha) * ax;
  g_lpf_ay = kAccelLpfAlpha * g_lpf_ay + (1.0f - kAccelLpfAlpha) * ay;
  g_lpf_az = kAccelLpfAlpha * g_lpf_az + (1.0f - kAccelLpfAlpha) * az;
}

void updateTiltBaselineIdle(float ax, float ay, float az) {
  float nx = 0.0f;
  float ny = 0.0f;
  float nz = 1.0f;
  normalizeAccel(ax, ay, az, &nx, &ny, &nz);
  if (!g_tilt_baseline_valid) {
    g_baseline_ax = nx;
    g_baseline_ay = ny;
    g_baseline_az = nz;
    g_tilt_baseline_valid = true;
    return;
  }
  g_baseline_ax = kTiltBaselineEmaAlpha * g_baseline_ax + (1.0f - kTiltBaselineEmaAlpha) * nx;
  g_baseline_ay = kTiltBaselineEmaAlpha * g_baseline_ay + (1.0f - kTiltBaselineEmaAlpha) * ny;
  g_baseline_az = kTiltBaselineEmaAlpha * g_baseline_az + (1.0f - kTiltBaselineEmaAlpha) * nz;
  normalizeAccel(g_baseline_ax, g_baseline_ay, g_baseline_az, &g_baseline_ax, &g_baseline_ay,
                 &g_baseline_az);
}

void snapshotTiltBaselineAtTrialStart() {
  float nx = 0.0f;
  float ny = 0.0f;
  float nz = 1.0f;
  normalizeAccel(g_lpf_ax, g_lpf_ay, g_lpf_az, &nx, &ny, &nz);
  g_baseline_ax = nx;
  g_baseline_ay = ny;
  g_baseline_az = nz;
  g_tilt_baseline_valid = true;
}

float computeTiltDegFromLpf() {
  if (!g_tilt_baseline_valid) {
    return 0.0f;
  }
  float nx = 0.0f;
  float ny = 0.0f;
  float nz = 1.0f;
  normalizeAccel(g_lpf_ax, g_lpf_ay, g_lpf_az, &nx, &ny, &nz);
  float dot = nx * g_baseline_ax + ny * g_baseline_ay + nz * g_baseline_az;
  if (dot > 1.0f) {
    dot = 1.0f;
  } else if (dot < -1.0f) {
    dot = -1.0f;
  }
  return acosf(dot) * 57.2957795f;
}

void recordTiltSample(TrialState state, float tilt_deg, float jerk_proxy) {
  if (jerk_proxy >= TILT_DYNAMIC_JERK_IGNORE) {
    return;
  }
  if (tilt_deg > g_metrics.tilt_deg_max) {
    g_metrics.tilt_deg_max = tilt_deg;
  }
  if (tilt_deg >= TILT_WARN_DEG) {
    g_metrics.tilt_over_limit_time_ms += kSamplePeriodMs;
    if (tilt_deg >= TILT_BAD_DEG) {
      g_metrics.tilt_over_limit_count++;
    }
  }
  const float t2 = tilt_deg * tilt_deg;
  if (state == TrialState::Approach) {
    g_metrics.course_tilt_sumsq += t2;
    g_metrics.course_tilt_samples++;
  } else if (state == TrialState::Hover || state == TrialState::Dock) {
    g_metrics.hover_tilt_sumsq += t2;
    g_metrics.hover_tilt_samples++;
  }
}

void updateCoursePauseMetrics(float gyro_mag, float jerk_proxy, unsigned long now) {
  const bool paused = gyro_mag < COURSE_PAUSE_GYRO_THRESH && jerk_proxy < COURSE_PAUSE_JERK_THRESH;
  if (paused) {
    if (!g_course_in_pause) {
      g_course_pause_start_ms = now;
      g_course_in_pause = true;
    } else if (now - g_course_pause_start_ms >= COURSE_PAUSE_MIN_MS) {
      g_metrics.course_pause_time_ms += kSamplePeriodMs;
    }
  } else {
    g_course_in_pause = false;
    g_course_pause_start_ms = 0;
  }
}

void updateTrialMetricsForSample(TrialState state, float gyro_mag, float jerk_proxy,
                               bool is_stable, bool is_occluded, float occlusion_pct,
                               float tilt_deg) {
  recordTiltSample(state, tilt_deg, jerk_proxy);

  if (state == TrialState::Approach) {
    g_metrics.course_sample_count++;
    g_metrics.course_gyro_sum += gyro_mag;
    g_metrics.course_gyro_sumsq += gyro_mag * gyro_mag;
    if (gyro_mag > g_metrics.course_gyro_max) {
      g_metrics.course_gyro_max = gyro_mag;
    }
    g_metrics.course_jerk_sum += jerk_proxy;
    g_metrics.course_jerk_sumsq += jerk_proxy * jerk_proxy;
    if (jerk_proxy > g_metrics.course_jerk_max) {
      g_metrics.course_jerk_max = jerk_proxy;
    }
    if (gyro_mag > COURSE_GYRO_SPIKE_THRESH) {
      g_metrics.course_gyro_spike_count++;
    }
    if (jerk_proxy > COURSE_JERK_SPIKE_THRESH) {
      g_metrics.course_jerk_spike_count++;
    }
    if (gyro_mag > COURSE_WOBBLE_GYRO_THRESH && g_course_prev_wobble_high) {
      g_metrics.course_wobble_events++;
    }
    g_course_prev_wobble_high = gyro_mag > COURSE_WOBBLE_GYRO_THRESH;
    updateCoursePauseMetrics(gyro_mag, jerk_proxy, millis());
  } else if (state == TrialState::Hover) {
    g_metrics.hover_total_samples++;
    g_metrics.hover_gyro_sum += gyro_mag;
    g_metrics.hover_gyro_sumsq += gyro_mag * gyro_mag;
    g_metrics.hover_jerk_sum += jerk_proxy;
    g_metrics.hover_jerk_sumsq += jerk_proxy * jerk_proxy;
    if (is_occluded) {
      g_metrics.hover_occluded_samples++;
      g_metrics.occlusion_pct_sum_hover += occlusion_pct;
    }
    if (is_stable) {
      g_metrics.hover_stable_samples++;
    } else {
      g_metrics.hover_unstable_sample_count++;
    }
    if (gyro_mag > HOVER_GYRO_SPIKE_THRESH) {
      g_metrics.hover_gyro_spike_count++;
    }
    if (jerk_proxy > HOVER_JERK_SPIKE_THRESH) {
      g_metrics.hover_jerk_spike_count++;
    }
  } else if (state == TrialState::Dock) {
    if (jerk_proxy > g_metrics.dock_jerk_peak_recent) {
      g_metrics.dock_jerk_peak_recent = jerk_proxy;
    }
    if (gyro_mag > g_metrics.dock_gyro_peak_recent) {
      g_metrics.dock_gyro_peak_recent = gyro_mag;
    }
  }
}

bool readRgbClearBurst(uint16_t *clear, uint16_t *r, uint16_t *g, uint16_t *b) {
  if (!clear || !r || !g || !b) {
    return false;
  }
  Wire.beginTransmission(kApdsAddr);
  Wire.write(APDS9960_CDATAL);
  if (Wire.endTransmission(false) != 0) {
    return false;
  }
  if (Wire.requestFrom(kApdsAddr, static_cast<uint8_t>(8)) != 8) {
    return false;
  }
  const uint8_t cl = Wire.read();
  const uint8_t ch = Wire.read();
  const uint8_t rl = Wire.read();
  const uint8_t rh = Wire.read();
  const uint8_t gl = Wire.read();
  const uint8_t gh = Wire.read();
  const uint8_t bl = Wire.read();
  const uint8_t bh = Wire.read();
  *clear = static_cast<uint16_t>(cl) | (static_cast<uint16_t>(ch) << 8);
  *r = static_cast<uint16_t>(rl) | (static_cast<uint16_t>(rh) << 8);
  *g = static_cast<uint16_t>(gl) | (static_cast<uint16_t>(gh) << 8);
  *b = static_cast<uint16_t>(bl) | (static_cast<uint16_t>(bh) << 8);
  return true;
}

void computeNorms(uint16_t r, uint16_t g, uint16_t b, float *rn, float *gn, float *bn) {
  const float sum = static_cast<float>(r) + static_cast<float>(g) + static_cast<float>(b);
  if (sum <= 0.0f) {
    *rn = *gn = *bn = 0.0f;
    return;
  }
  *rn = static_cast<float>(r) / sum;
  *gn = static_cast<float>(g) / sum;
  *bn = static_cast<float>(b) / sum;
}

bool initApds() {
  if (!apds.begin()) {
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
  uint16_t c = 0;
  uint16_t r = 0;
  uint16_t g = 0;
  uint16_t b = 0;
  return readRgbClearBurst(&c, &r, &g, &b);
}

void updateBaselineEma(uint16_t clear) {
  if (clear == 0) {
    return;
  }
  if (!g_baseline_valid) {
    g_baseline_clear = clear;
    g_baseline_valid = true;
    return;
  }
  const float ema =
      kBaselineEmaAlpha * static_cast<float>(g_baseline_clear) +
      (1.0f - kBaselineEmaAlpha) * static_cast<float>(clear);
  g_baseline_clear = static_cast<uint16_t>(ema);
}

void resetApdsOcclusionLatch() { g_apds_occlusion_latched = false; }

void captureBaselineManual() {
  uint16_t c = 0;
  uint16_t r = 0;
  uint16_t g = 0;
  uint16_t b = 0;
  if (readRgbClearBurst(&c, &r, &g, &b) && c > 0) {
    g_baseline_clear = c;
    g_baseline_valid = true;
    resetApdsOcclusionLatch();
    pushEvent("BASELINE_SET");
    processAllPendingEvents(millis());
  }
}

void cycleAlsGain() {
  if (!g_apds_ok) {
    return;
  }
  g_gain_index = (g_gain_index + 1) % 4;
  apds.setAmbientLightGain(kGainCodes[g_gain_index]);
  pushEvent("GAIN_CHANGED");
}

void initDebouncedButton(DebouncedButton *btn, int pin) {
  if (btn == nullptr) {
    return;
  }
  btn->pin = static_cast<uint8_t>(pin);
  btn->last_raw = digitalRead(pin) == LOW;
  btn->raw_pressed = btn->last_raw;
  btn->stable_pressed = btn->last_raw;
  btn->prev_stable_pressed = btn->stable_pressed;
  btn->last_raw_change_ms = millis();
  btn->stable_pressed_since_ms = btn->stable_pressed ? btn->last_raw_change_ms : 0;
}

void updateDebouncedButton(DebouncedButton *btn) {
  if (btn == nullptr || btn->pin == 255) {
    return;
  }
  btn->pressed_edge = false;
  btn->released_edge = false;
  const bool raw = digitalRead(btn->pin) == LOW;
  btn->raw_pressed = raw;
  const unsigned long now = millis();
  if (raw != btn->last_raw) {
    btn->last_raw_change_ms = now;
    btn->last_raw = raw;
  }
  if ((now - btn->last_raw_change_ms) >= btn->debounce_ms && raw != btn->stable_pressed) {
    btn->prev_stable_pressed = btn->stable_pressed;
    btn->stable_pressed = raw;
    if (btn->stable_pressed && !btn->prev_stable_pressed) {
      btn->pressed_edge = true;
      btn->stable_pressed_since_ms = now;
    }
    if (!btn->stable_pressed && btn->prev_stable_pressed) {
      btn->released_edge = true;
      btn->stable_pressed_since_ms = 0;
    }
  }
  if (btn->stable_pressed && btn->stable_pressed_since_ms > 0) {
    btn->pressed_ms = now - btn->stable_pressed_since_ms;
  } else {
    btn->pressed_ms = 0;
  }
}

bool buttonStablePressedFor(const DebouncedButton &btn, unsigned long ms) {
  return btn.stable_pressed && btn.pressed_ms >= ms;
}

void updateButtonConsumedLatch(DebouncedButton &btn, bool *consumed) {
  if (consumed == nullptr) {
    return;
  }
  if (!btn.stable_pressed) {
    *consumed = false;
  }
}

void printButtonStatus() {
  Serial.println(F("# buttons"));
  Serial.print(F("start raw="));
  Serial.print(startButton.raw_pressed ? 1 : 0);
  Serial.print(F(" stable="));
  Serial.print(startButton.stable_pressed ? 1 : 0);
  Serial.print(F(" pressed_ms="));
  Serial.print(startButton.pressed_ms);
  Serial.print(F(" consumed="));
  Serial.println(g_start_action_consumed ? 1 : 0);
  Serial.print(F("end raw="));
  Serial.print(endButton.raw_pressed ? 1 : 0);
  Serial.print(F(" stable="));
  Serial.print(endButton.stable_pressed ? 1 : 0);
  Serial.print(F(" pressed_ms="));
  Serial.print(endButton.pressed_ms);
  Serial.print(F(" consumed="));
  Serial.println(g_end_action_consumed ? 1 : 0);
}

void transitionTo(TrialState next, const char *event) {
  g_state = next;
  g_state_enter_ms = millis();
  if (event != nullptr) {
    pushEvent(event);
  }
  if (next == TrialState::Hover) {
    g_hover_ms = 0;
    g_last_hover_accum_ms = millis();
    g_occlusion_lost_ms = 0;
  }
  if (next == TrialState::Dock) {
    g_dock_complete_consumed = false;
    g_dock_enter_ms = millis();
    g_metrics.dock_jerk_peak_recent = 0.0f;
    g_metrics.dock_gyro_peak_recent = 0.0f;
  }
}

void returnToIdleFromComplete() {
  g_state = TrialState::Idle;
  g_hover_ms = 0;
  g_state_enter_ms = millis();
  g_dock_complete_consumed = false;
  resetApdsOcclusionLatch();
  digitalWrite(STATUS_LED_PIN, LOW);
  pushEvent("RETURN_TO_IDLE");
}

void resetTrialToIdle() {
  g_state = TrialState::Idle;
  g_hover_ms = 0;
  g_state_enter_ms = millis();
  g_dock_complete_consumed = false;
  g_start_action_consumed = false;
  g_end_action_consumed = false;
  resetApdsOcclusionLatch();
  digitalWrite(STATUS_LED_PIN, LOW);
  pushEvent("RESET");
}

void startTrial() {
  if (g_state != TrialState::Idle && g_state != TrialState::Complete) {
    return;
  }
  ++g_trial_id;
  g_sample_index = 0;
  resetTrialMetrics();
  resetApdsOcclusionLatch();
  snapshotTiltBaselineAtTrialStart();
  g_roll_idx = 0;
  g_roll_count = 0;
  g_last_live_print_ms = 0;
  strncpy(g_current_live_issue, "Smooth", sizeof(g_current_live_issue) - 1);
  g_metrics.trial_id = g_trial_id;
  transitionTo(TrialState::Approach, "TRIAL_START");
}

void handleButtons() {
  updateButtonConsumedLatch(startButton, &g_start_action_consumed);
  updateButtonConsumedLatch(endButton, &g_end_action_consumed);

  if (g_state == TrialState::Idle || g_state == TrialState::Complete) {
    if (buttonStablePressedFor(startButton, kButtonActionHoldMs) &&
        !g_start_action_consumed) {
      g_start_action_consumed = true;
      startTrial();
      processAllPendingEvents(millis());
    }
  }

  if (g_state == TrialState::Dock && !g_dock_complete_consumed) {
    if (buttonStablePressedFor(endButton, kEndHoldMs) && !g_end_action_consumed) {
      g_end_action_consumed = true;
      g_dock_complete_consumed = true;
      transitionTo(TrialState::Complete, "DOCK_COMPLETE");
      digitalWrite(STATUS_LED_PIN, HIGH);
      processAllPendingEvents(millis());
    }
  }

  if (g_state == TrialState::Complete) {
    if (buttonStablePressedFor(endButton, kEndHoldMs) && !g_end_action_consumed) {
      g_end_action_consumed = true;
      returnToIdleFromComplete();
      processAllPendingEvents(millis());
    }
  }
}

void printCsvHeader() {
  Serial.println(
      F("trial_id,sample,t_ms,state,ax,ay,az,gx,gy,gz,acc_mag,gyro_mag,"
        "jerk_proxy,clear,red,green,blue,baseline_clear,clear_delta,occlusion_pct,"
        "is_occluded,start_raw,start_stable,start_pressed_edge,end_raw,end_stable,"
        "end_pressed_ms,dock_complete_consumed,is_stable,hover_ms,event"));
}

bool readMotion(float *ax, float *ay, float *az, float *gx, float *gy, float *gz,
                float *acc_mag, float *gyro_mag, float *jerk_proxy) {
  if (!g_imu_ok) {
    *ax = *ay = *az = *gx = *gy = *gz = 0.0f;
    *acc_mag = *gyro_mag = *jerk_proxy = 0.0f;
    return false;
  }
  *ax = imu.getAccelX(false);
  *ay = imu.getAccelY(false);
  *az = imu.getAccelZ(false);
  *gx = imu.getGyroX(false);
  *gy = imu.getGyroY(false);
  *gz = imu.getGyroZ(false);
  *acc_mag = sqrtf((*ax) * (*ax) + (*ay) * (*ay) + (*az) * (*az));
  *gyro_mag = sqrtf((*gx) * (*gx) + (*gy) * (*gy) + (*gz) * (*gz));
  const unsigned long now = millis();
  *jerk_proxy = 0.0f;
  if (g_prev_motion_ms > 0) {
    const float dt = static_cast<float>(now - g_prev_motion_ms) / 1000.0f;
    if (dt > 0.0f) {
      *jerk_proxy = fabsf(*acc_mag - g_prev_acc_mag) / dt;
    }
  }
  g_prev_acc_mag = *acc_mag;
  g_prev_motion_ms = now;
  return true;
}

struct ApdsFrame {
  uint16_t clear = 0;
  uint16_t r = 0;
  uint16_t g = 0;
  uint16_t b = 0;
  float occlusion_pct = 0.0f;
  bool is_occluded = false;
};

ApdsFrame g_last_apds_frame;

void pollApdsFrame(unsigned long now);
const char *currentLiveFeedback();
void updateLiveIssue(TrialState state, const ApdsFrame &f, bool is_stable, float gyro_mag,
                     float jerk_proxy);
void maybePrintLiveFeedback(unsigned long now, const ApdsFrame &f, bool is_stable, float gyro_mag,
                            float jerk_proxy);
void updateOled(const ApdsFrame &f, bool is_stable);

const char *currentLiveFeedback() { return g_current_live_issue; }

void updateLiveIssue(TrialState state, const ApdsFrame &f, bool is_stable, float gyro_mag,
                     float jerk_proxy) {
  float roll_gyro = 0.0f;
  float roll_jerk = 0.0f;
  float roll_spike = 0.0f;
  float roll_tilt = 0.0f;
  rollingWindowStats(&roll_gyro, &roll_jerk, &roll_spike, &roll_tilt);

  if (state == TrialState::Approach) {
    if (g_metrics.course_pause_time_ms >= COURSE_PAUSE_MIN_MS) {
      strncpy(g_current_live_issue, "Keep moving", sizeof(g_current_live_issue) - 1);
    } else if (roll_tilt >= TILT_WARN_DEG) {
      strncpy(g_current_live_issue, "Level handle", sizeof(g_current_live_issue) - 1);
    } else if (roll_jerk > effCourseJerkRmsBad() * 0.85f ||
               roll_spike > effCourseSpikeRateBad() * 0.85f) {
      strncpy(g_current_live_issue, "Slow down", sizeof(g_current_live_issue) - 1);
    } else if (roll_gyro > effCourseGyroRmsBad() * 0.85f) {
      strncpy(g_current_live_issue, "Steady rot.", sizeof(g_current_live_issue) - 1);
    } else {
      strncpy(g_current_live_issue, "Smooth course", sizeof(g_current_live_issue) - 1);
    }
  } else if (state == TrialState::Hover) {
    if (!f.is_occluded) {
      strncpy(g_current_live_issue, "Cover target", sizeof(g_current_live_issue) - 1);
    } else if (!is_stable) {
      strncpy(g_current_live_issue, "Hold still", sizeof(g_current_live_issue) - 1);
    } else if (roll_tilt >= TILT_WARN_DEG) {
      strncpy(g_current_live_issue, "Level handle", sizeof(g_current_live_issue) - 1);
    } else {
      strncpy(g_current_live_issue, "Good hover", sizeof(g_current_live_issue) - 1);
    }
  } else if (state == TrialState::Dock) {
    if (jerk_proxy > effDockJerkBad() * 0.7f) {
      strncpy(g_current_live_issue, "Too hard", sizeof(g_current_live_issue) - 1);
    } else {
      strncpy(g_current_live_issue, "Gentle press", sizeof(g_current_live_issue) - 1);
    }
  } else {
    strncpy(g_current_live_issue, "Smooth", sizeof(g_current_live_issue) - 1);
  }
  g_current_live_issue[sizeof(g_current_live_issue) - 1] = '\0';
}

void maybePrintLiveFeedback(unsigned long now, const ApdsFrame &f, bool is_stable, float gyro_mag,
                            float jerk_proxy) {
  if (!g_metrics.got_trial_start || g_metrics.got_dock_complete) {
    return;
  }
  if (g_last_live_print_ms > 0 &&
      static_cast<long>(now - g_last_live_print_ms) < static_cast<long>(kLivePrintMs)) {
    return;
  }
  g_last_live_print_ms = now;
  updateLiveIssue(g_state, f, is_stable, gyro_mag, jerk_proxy);

  float roll_gyro = 0.0f;
  float roll_jerk = 0.0f;
  float roll_spike = 0.0f;
  rollingWindowStats(&roll_gyro, &roll_jerk, &roll_spike, nullptr);

  Serial.print(F("LIVE,trial="));
  Serial.print(g_trial_id);
  Serial.print(F(",state="));
  Serial.print(stateName(g_state));
  Serial.print(F(",score="));
  Serial.print(computeActiveScoreEstimate());
  Serial.print(F(",issue="));
  Serial.print(g_current_live_issue);
  if (g_state == TrialState::Approach) {
    Serial.print(F(",gyro_rms="));
    Serial.print(roll_gyro, 1);
    Serial.print(F(",jerk_rms="));
    Serial.print(roll_jerk, 0);
    Serial.print(F(",spike_rate="));
    Serial.print(roll_spike, 2);
  } else if (g_state == TrialState::Hover) {
    Serial.print(F(",hover="));
    Serial.print(g_hover_ms);
    Serial.print(F("/"));
    Serial.print(kHoverDwellMs);
    Serial.print(F(",stable="));
    Serial.print(is_stable ? 1 : 0);
    Serial.print(F(",occ="));
    Serial.print(f.is_occluded ? 1 : 0);
  } else if (g_state == TrialState::Dock) {
    Serial.print(F(",dock_ms="));
    Serial.print(g_metrics.hover_complete_ms > 0 ? now - g_metrics.hover_complete_ms : 0);
  }
  Serial.println();
}

float computeOcclusionPct(uint16_t clear) {
  if (!g_baseline_valid || g_baseline_clear == 0) {
    return 0.0f;
  }
  return 100.0f * (static_cast<float>(g_baseline_clear) - static_cast<float>(clear)) /
         static_cast<float>(g_baseline_clear);
}

void calibSampleStats(const float *samples, uint8_t count, float *min_out, float *max_out,
                      float *mean_out) {
  if (min_out) {
    *min_out = 0.0f;
  }
  if (max_out) {
    *max_out = 0.0f;
  }
  if (mean_out) {
    *mean_out = 0.0f;
  }
  if (samples == nullptr || count == 0) {
    return;
  }
  float mn = samples[0];
  float mx = samples[0];
  float sum = samples[0];
  for (uint8_t i = 1; i < count; ++i) {
    if (samples[i] < mn) {
      mn = samples[i];
    }
    if (samples[i] > mx) {
      mx = samples[i];
    }
    sum += samples[i];
  }
  if (min_out) {
    *min_out = mn;
  }
  if (max_out) {
    *max_out = mx;
  }
  if (mean_out) {
    *mean_out = sum / static_cast<float>(count);
  }
}

void printCalibProgress() {
  Serial.print(F("CALIB progress open="));
  Serial.print(g_calib_open_count);
  Serial.print(F("/"));
  Serial.print(kCalibMaxSamples);
  Serial.print(F(" covered="));
  Serial.print(g_calib_covered_count);
  Serial.print(F("/"));
  Serial.println(kCalibMaxSamples);
}

void clearOcclusionCalib() {
  g_calib_open_count = 0;
  g_calib_covered_count = 0;
  Serial.println(F("CALIB cleared (press o=open, v=covered, ~10 each)"));
}

void forcePollApdsFrame() {
  g_last_apds_poll_ms = 0;
  pollApdsFrame(millis());
}

bool estimateOcclusionThresholds() {
  if (g_calib_open_count < kCalibMinSamples ||
      g_calib_covered_count < kCalibMinSamples) {
    Serial.print(F("CALIB need >= "));
    Serial.print(kCalibMinSamples);
    Serial.println(F(" open and covered samples (o / c)"));
    return false;
  }

  float open_min = 0.0f;
  float open_max = 0.0f;
  float open_mean = 0.0f;
  float covered_min = 0.0f;
  float covered_max = 0.0f;
  float covered_mean = 0.0f;
  calibSampleStats(g_calib_open, g_calib_open_count, &open_min, &open_max, &open_mean);
  calibSampleStats(g_calib_covered, g_calib_covered_count, &covered_min, &covered_max,
                   &covered_mean);

  const float gap = covered_min - open_max;
  Serial.println(F("CALIB stats"));
  Serial.print(F("  open    mean="));
  Serial.print(open_mean, 1);
  Serial.print(F("% max="));
  Serial.print(open_max, 1);
  Serial.println(F("%"));
  Serial.print(F("  covered mean="));
  Serial.print(covered_mean, 1);
  Serial.print(F("% min="));
  Serial.print(covered_min, 1);
  Serial.println(F("%"));
  Serial.print(F("  separation (covered_min - open_max)="));
  Serial.print(gap, 1);
  Serial.println(F("%"));

  if (gap < 5.0f) {
    Serial.println(F("CALIB_WARN: low separation; check baseline, gain (g), or lighting"));
  }

  float enter = open_max + 0.70f * gap;
  float exit = open_max + 0.25f * gap;
  constexpr float kMinHysteresisPct = 5.0f;
  if (enter - exit < kMinHysteresisPct) {
    exit = enter - kMinHysteresisPct;
  }
  if (enter < open_mean + 6.0f) {
    enter = open_mean + 6.0f;
  }
  if (exit < 3.0f) {
    exit = 3.0f;
  }
  if (enter > 75.0f) {
    enter = 75.0f;
  }
  if (exit > enter - kMinHysteresisPct) {
    exit = enter - kMinHysteresisPct;
  }

  g_occlusion_enter_pct = enter;
  g_occlusion_exit_pct = exit;
  resetApdsOcclusionLatch();

  Serial.println(F("CALIB_APPLIED"));
  Serial.print(F("  enter="));
  Serial.print(g_occlusion_enter_pct, 1);
  Serial.print(F("% exit="));
  Serial.print(g_occlusion_exit_pct, 1);
  Serial.println(F("%"));
  Serial.println(F("  (higher enter = less sensitive; re-run z if lighting changes)"));
  return true;
}

void recordOcclusionCalibSample(bool covered) {
  if (!g_apds_ok) {
    Serial.println(F("CALIB_ERR: APDS not ready"));
    return;
  }
  if (!g_baseline_valid) {
    Serial.println(F("CALIB_ERR: press z for baseline first (target OPEN)"));
    return;
  }

  forcePollApdsFrame();
  const float occ = computeOcclusionPct(g_last_apds_frame.clear);

  if (covered) {
    if (g_calib_covered_count >= kCalibMaxSamples) {
      Serial.println(F("CALIB covered full (10/10); press t to tune or l to clear"));
      return;
    }
    g_calib_covered[g_calib_covered_count++] = occ;
    Serial.print(F("CALIB covered["));
    Serial.print(g_calib_covered_count);
    Serial.print(F("/"));
    Serial.print(kCalibMaxSamples);
    Serial.print(F("] occ="));
    Serial.print(occ, 1);
    Serial.print(F("% clear="));
    Serial.println(g_last_apds_frame.clear);
  } else {
    if (g_calib_open_count >= kCalibMaxSamples) {
      Serial.println(F("CALIB open full (10/10); press t to tune or l to clear"));
      return;
    }
    g_calib_open[g_calib_open_count++] = occ;
    Serial.print(F("CALIB open["));
    Serial.print(g_calib_open_count);
    Serial.print(F("/"));
    Serial.print(kCalibMaxSamples);
    Serial.print(F("] occ="));
    Serial.print(occ, 1);
    Serial.print(F("% clear="));
    Serial.println(g_last_apds_frame.clear);
  }

  printCalibProgress();
  if (g_calib_open_count >= kCalibMaxSamples &&
      g_calib_covered_count >= kCalibMaxSamples) {
    Serial.println(F("CALIB auto-tune (10+10 samples)"));
    estimateOcclusionThresholds();
  }
}

void applyOcclusionHysteresis(ApdsFrame *f) {
  if (f == nullptr) {
    return;
  }
  if (!g_baseline_valid || g_baseline_clear == 0) {
    g_apds_occlusion_latched = false;
    f->is_occluded = false;
    f->occlusion_pct = 0.0f;
    return;
  }

  f->occlusion_pct = computeOcclusionPct(f->clear);

  if (!g_apds_occlusion_latched) {
    if (f->occlusion_pct >= g_occlusion_enter_pct) {
      g_apds_occlusion_latched = true;
    }
  } else if (f->occlusion_pct < g_occlusion_exit_pct) {
    g_apds_occlusion_latched = false;
  }

  f->is_occluded = g_apds_occlusion_latched;
}

void pollApdsFrame(unsigned long now) {
  if (!g_apds_ok) {
    return;
  }
  if (g_last_apds_poll_ms > 0 &&
      static_cast<long>(now - g_last_apds_poll_ms) < static_cast<long>(kApdsPollMs)) {
    return;
  }
  g_last_apds_poll_ms = now;

  ApdsFrame fresh;
  uint16_t r = 0;
  uint16_t g = 0;
  uint16_t b = 0;
  if (!readRgbClearBurst(&fresh.clear, &r, &g, &b) || fresh.clear == 0) {
    g_apds_consecutive_fail_count++;
    g_apds_read_fail_count++;
    if (g_apds_consecutive_fail_count >= kApdsFailWarnThreshold && !g_apds_warn_emitted) {
      pushEvent("APDS_READ_WARN");
      g_apds_warn_emitted = true;
    }
    return;
  }

  g_apds_consecutive_fail_count = 0;
  g_apds_warn_emitted = false;
  fresh.r = r;
  fresh.g = g;
  fresh.b = b;
  applyOcclusionHysteresis(&fresh);
  g_last_apds_frame = fresh;
}

const ApdsFrame &getApdsFrame() { return g_last_apds_frame; }

void maybeUpdateOled(unsigned long now) {
  if (!g_oled_ok) {
    return;
  }
  if (static_cast<long>(now - g_last_oled_ms) < static_cast<long>(kOledUpdateMs)) {
    return;
  }
  updateOled(g_last_apds_frame, g_last_is_stable);
}

bool computeImuStable(float gyro_mag, float jerk_proxy) {
  return gyro_mag <= kStableGyroMax && jerk_proxy <= kStableJerkMax;
}

bool computeStability(float gyro_mag, float jerk_proxy, bool is_occluded) {
  const bool imu_stable = computeImuStable(gyro_mag, jerk_proxy);
  if (!USE_APDS_OCCLUSION_GATE) {
    return imu_stable;
  }
  return imu_stable && is_occluded;
}

bool tryDockCompleteSerial(bool serial_d) {
  if (!serial_d || g_state != TrialState::Dock || g_dock_complete_consumed) {
    return false;
  }
  if (millis() - g_dock_enter_ms < kDockIgnoreMs) {
    return false;
  }
  g_dock_complete_consumed = true;
  return true;
}

void updateStateMachine(const ApdsFrame &apds_frame, bool imu_stable) {
  const unsigned long now = millis();
  switch (g_state) {
    case TrialState::Idle:
      if (g_baseline_valid) {
        updateBaselineEma(apds_frame.clear);
      } else if (apds_frame.clear > 0) {
        g_baseline_clear = apds_frame.clear;
        g_baseline_valid = true;
      }
      break;
    case TrialState::Approach:
      g_hover_ms = 0;
      if (apds_frame.is_occluded) {
        transitionTo(TrialState::Hover, "HOVER_ENTER");
      }
      break;
    case TrialState::Hover: {
      const bool dwell_ok = apds_frame.is_occluded && imu_stable;
      if (dwell_ok) {
        const unsigned long dt = now - g_last_hover_accum_ms;
        g_hover_ms += dt;
        g_last_hover_accum_ms = now;
        g_occlusion_lost_ms = 0;
      } else {
        g_last_hover_accum_ms = now;
        if (!apds_frame.is_occluded) {
          if (g_occlusion_lost_ms == 0) {
            g_occlusion_lost_ms = now;
          } else if (now - g_occlusion_lost_ms >= kOcclusionLossResetMs) {
            g_hover_ms = 0;
            pushEvent("HOVER_RESET");
            g_occlusion_lost_ms = 0;
          }
        } else {
          g_occlusion_lost_ms = 0;
        }
      }
      if (g_hover_ms >= kHoverDwellMs) {
        transitionTo(TrialState::Dock, "HOVER_COMPLETE");
      }
      break;
    }
    case TrialState::Dock:
    case TrialState::Complete:
      break;
  }
}

void handleSerialCommand(char c, bool *dock_sim) {
  switch (c) {
    case 's':
    case 'S':
      if (g_state == TrialState::Idle || g_state == TrialState::Complete) {
        startTrial();
        processAllPendingEvents(millis());
      }
      break;
    case 'r':
    case 'R':
      resetTrialToIdle();
      processAllPendingEvents(millis());
      break;
    case 'd':
    case 'D':
      if (g_state == TrialState::Dock) {
        *dock_sim = true;
      }
      break;
    case 'z':
    case 'Z':
      captureBaselineManual();
      break;
    case 'g':
    case 'G':
      cycleAlsGain();
      break;
    case 'p':
    case 'P':
      printScoreBreakdown();
      break;
    case 'q':
    case 'Q':
      printScoringThresholds();
      break;
    case 'x':
    case 'X':
      g_stream_raw_csv = !g_stream_raw_csv;
      Serial.print(F("# raw CSV stream "));
      Serial.println(g_stream_raw_csv ? F("ON") : F("OFF"));
      if (g_stream_raw_csv) {
        printCsvHeader();
      }
      break;
    case 'b':
    case 'B':
      printButtonStatus();
      break;
    case 'o':
      recordOcclusionCalibSample(false);
      break;
    case 'v':
    case 'V':
      recordOcclusionCalibSample(true);
      break;
    case 'c':
      applyScoreCalibrationFromLastTrial();
      break;
    case 'C':
      clearScoreCalibration();
      break;
    case 't':
    case 'T':
      estimateOcclusionThresholds();
      break;
    case 'l':
    case 'L':
      clearOcclusionCalib();
      break;
    default:
      break;
  }
}

void drawProgressBar(int x, int y, int w, int h, float fraction) {
  if (fraction < 0.0f) {
    fraction = 0.0f;
  }
  if (fraction > 1.0f) {
    fraction = 1.0f;
  }
  display.drawRect(x, y, w, h, SSD1306_WHITE);
  const int inner_w = w - 2;
  const int inner_h = h - 2;
  const int fill_w = static_cast<int>(static_cast<float>(inner_w) * fraction);
  if (fill_w > 0 && inner_h > 0) {
    display.fillRect(x + 1, y + 1, fill_w, inner_h, SSD1306_WHITE);
  }
}

void oledTextLarge(int16_t x, int16_t y, const char *text) {
  display.setTextSize(2);
  display.setCursor(x, y);
  display.println(text);
}

void oledTextLarge(int16_t x, int16_t y, const __FlashStringHelper *text) {
  display.setTextSize(2);
  display.setCursor(x, y);
  display.println(text);
}

void oledTextSmall(int16_t x, int16_t y, const char *text) {
  display.setTextSize(1);
  display.setCursor(x, y);
  display.println(text);
}

void oledTextSmall(int16_t x, int16_t y, const __FlashStringHelper *text) {
  display.setTextSize(1);
  display.setCursor(x, y);
  display.println(text);
}

void updateOled(const ApdsFrame &f, bool is_stable) {
  if (!g_oled_ok) {
    return;
  }
  const unsigned long now = millis();
  if (static_cast<long>(now - g_last_oled_ms) < static_cast<long>(kOledUpdateMs)) {
    return;
  }
  g_last_oled_ms = now;

  display.clearDisplay();
  display.setTextColor(SSD1306_WHITE);

  switch (g_state) {
    case TrialState::Idle:
      oledTextLarge(0, 0, F("IDLE"));
      {
        char buf[24];
        snprintf(buf, sizeof(buf), "Trial %u", static_cast<unsigned>(g_trial_id + 1));
        oledTextSmall(0, 20, buf);
      }
      if (g_last_completed_trial_score > 0) {
        char buf[24];
        snprintf(buf, sizeof(buf), "Prev: %d/100", g_last_completed_trial_score);
        oledTextSmall(0, 32, buf);
        if (g_last_feedback[0] != '\0') {
          oledTextSmall(0, 44, g_last_feedback);
        }
      }
      oledTextSmall(0, 54, F("GREEN START"));
      break;

    case TrialState::Approach:
      oledTextLarge(0, 0, F("APPROACH"));
      oledTextSmall(0, 20, currentLiveFeedback());
      {
        char buf[20];
        snprintf(buf, sizeof(buf), "Occ: %.0f%%", f.occlusion_pct);
        oledTextSmall(0, 32, buf);
      }
      oledTextSmall(0, 54, F("Cover target"));
      break;

    case TrialState::Hover: {
      oledTextLarge(0, 0, F("HOVER"));
      oledTextSmall(0, 20, F("Hold steady"));
      const float prog =
          static_cast<float>(g_hover_ms) / static_cast<float>(kHoverDwellMs);
      {
        char buf[20];
        snprintf(buf, sizeof(buf), "%.1f/%.1fs", prog * kHoverDwellMs / 1000.0f,
                 kHoverDwellMs / 1000.0f);
        oledTextSmall(0, 32, buf);
      }
      drawProgressBar(4, 44, 120, 10, prog);
      oledTextSmall(0, 56, currentLiveFeedback());
      break;
    }

    case TrialState::Dock: {
      oledTextLarge(0, 0, F("DOCK"));
      oledTextSmall(0, 20, currentLiveFeedback());
      {
        char buf[24];
        snprintf(buf, sizeof(buf), "Hover: %d/30", g_previous_phase_score);
        oledTextSmall(0, 32, buf);
      }
      oledTextSmall(0, 54, F("RED END"));
      if (g_metrics.hover_complete_ms > 0) {
        char buf[16];
        snprintf(buf, sizeof(buf), "Dock %lus",
                 (now - g_metrics.hover_complete_ms) / 1000UL);
        oledTextSmall(72, 32, buf);
      }
      break;
    }

    case TrialState::Complete:
      oledTextLarge(0, 0, F("SCORE"));
      {
        char buf[16];
        snprintf(buf, sizeof(buf), "%d/100", g_metrics.total_score);
        oledTextLarge(0, 18, buf);
      }
      if (g_metrics.feedback[0] != '\0') {
        oledTextSmall(0, 36, g_metrics.feedback);
      }
      if (g_metrics.got_dock_complete) {
        char buf[28];
        snprintf(buf, sizeof(buf), "A:%lus H:%lus D:%lus",
                 g_metrics.approach_time_ms / 1000UL, g_metrics.hover_time_ms / 1000UL,
                 g_metrics.dock_time_ms / 1000UL);
        oledTextSmall(0, 48, buf);
      }
      oledTextSmall(0, 54, F("RED RETURN"));
      break;
  }

  display.display();
}

void emitCsvRow(unsigned long t_ms, const ApdsFrame &f, float ax, float ay, float az,
                float gx, float gy, float gz, float acc_mag, float gyro_mag,
                float jerk_proxy, bool is_stable) {
  Serial.print(g_trial_id);
  Serial.print(',');
  Serial.print(g_sample_index++);
  Serial.print(',');
  Serial.print(t_ms);
  Serial.print(',');
  Serial.print(stateName(g_state));
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
  Serial.print(f.clear);
  Serial.print(',');
  Serial.print(0);
  Serial.print(',');
  Serial.print(0);
  Serial.print(',');
  Serial.print(0);
  Serial.print(',');
  Serial.print(g_baseline_clear);
  Serial.print(',');
  Serial.print(0, 1);
  Serial.print(',');
  Serial.print(f.occlusion_pct, 1);
  Serial.print(',');
  Serial.print(f.is_occluded ? 1 : 0);
  Serial.print(',');
  Serial.print(startButton.raw_pressed ? 1 : 0);
  Serial.print(',');
  Serial.print(startButton.stable_pressed ? 1 : 0);
  Serial.print(',');
  Serial.print(startButton.pressed_edge ? 1 : 0);
  Serial.print(',');
  Serial.print(endButton.raw_pressed ? 1 : 0);
  Serial.print(',');
  Serial.print(endButton.stable_pressed ? 1 : 0);
  Serial.print(',');
  Serial.print(endButton.pressed_ms);
  Serial.print(',');
  Serial.print(g_dock_complete_consumed ? 1 : 0);
  Serial.print(',');
  Serial.print(is_stable ? 1 : 0);
  Serial.print(',');
  Serial.print(g_hover_ms);
  Serial.print(',');
  Serial.println(g_last_csv_event);
}

}  // namespace

void setup() {
  Serial.begin(115200);
  delay(300);
  esp_log_level_set("Wire", ESP_LOG_NONE);

  pinMode(START_BUTTON_PIN, INPUT_PULLUP);
  pinMode(END_BUTTON_PIN, INPUT_PULLUP);
  pinMode(STATUS_LED_PIN, OUTPUT);
  digitalWrite(STATUS_LED_PIN, LOW);

  initDebouncedButton(&startButton, START_BUTTON_PIN);
  initDebouncedButton(&endButton, END_BUTTON_PIN);

  Serial.println();
  Serial.println(F("=== MYOSA Lap Trainer (scoring) ==="));
  Serial.println(F("BOOT: APDS occlusion + IMU scoring enabled"));
  Serial.print(F("APDS thresholds: enter="));
  Serial.print(g_occlusion_enter_pct, 0);
  Serial.print(F("%, exit="));
  Serial.print(g_occlusion_exit_pct, 0);
  Serial.println(F("%"));
  Serial.print(F("CSV debug: "));
  Serial.println(g_stream_raw_csv ? F("ON") : F("OFF"));

  Wire.begin();
  Wire.setClock(100000);
  delay(50);

  g_oled_ok = display.begin();
  g_apds_ok = initApds();
  g_imu_ok = imu.begin(false);

  Serial.print(F("OLED="));
  Serial.print(g_oled_ok ? 1 : 0);
  Serial.print(F(" APDS="));
  Serial.print(g_apds_ok ? 1 : 0);
  Serial.print(F(" IMU="));
  Serial.println(g_imu_ok ? 1 : 0);

  if (g_apds_ok) {
    captureBaselineManual();
    clearEventQueue();
  }

  Serial.println(F("Buttons: GREEN START | RED END / RETURN"));
  Serial.println(
      F("Serial: s start | d dock | r reset | z baseline | g gain | p score | q thresholds | x csv | b"));
  Serial.println(
      F("APDS: o=open v=covered x10 each, t=tune, l=clear | SCORE: c=cal ref trial C=clear cal"));
  Serial.println(F("COMPLETE: press RED RETURN -> IDLE"));
  if (g_stream_raw_csv) {
    printCsvHeader();
  }

  g_next_sample_ms = millis();
  pollApdsFrame(millis());
  updateOled(g_last_apds_frame, false);
}

void loop() {
  const unsigned long now = millis();

  updateDebouncedButton(&startButton);
  updateDebouncedButton(&endButton);

  bool serial_d = false;
  while (Serial.available() > 0) {
    handleSerialCommand(static_cast<char>(Serial.read()), &serial_d);
  }

  handleButtons();
  pollApdsFrame(now);
  processAllPendingEvents(now);
  maybeUpdateOled(now);

  if (static_cast<long>(now - g_next_sample_ms) < 0) {
    return;
  }
  g_next_sample_ms = now + kSamplePeriodMs;

  const ApdsFrame &frame = getApdsFrame();
  float ax = 0.0f;
  float ay = 0.0f;
  float az = 0.0f;
  float gx = 0.0f;
  float gy = 0.0f;
  float gz = 0.0f;
  float acc_mag = 0.0f;
  float gyro_mag = 0.0f;
  float jerk_proxy = 0.0f;
  readMotion(&ax, &ay, &az, &gx, &gy, &gz, &acc_mag, &gyro_mag, &jerk_proxy);
  updateAccelLpf(ax, ay, az);
  if (g_state == TrialState::Idle) {
    updateTiltBaselineIdle(ax, ay, az);
  }
  g_tilt_deg_current = computeTiltDegFromLpf();

  const bool imu_stable = computeImuStable(gyro_mag, jerk_proxy);
  const bool is_stable = computeStability(gyro_mag, jerk_proxy, frame.is_occluded);
  g_last_is_stable = is_stable;

  const bool is_spike =
      (g_state == TrialState::Approach &&
       (gyro_mag > COURSE_GYRO_SPIKE_THRESH || jerk_proxy > COURSE_JERK_SPIKE_THRESH)) ||
      (g_state == TrialState::Hover &&
       (gyro_mag > HOVER_GYRO_SPIKE_THRESH || jerk_proxy > HOVER_JERK_SPIKE_THRESH));
  pushRollingSample(gyro_mag, jerk_proxy, is_spike, g_tilt_deg_current);

  updateTrialMetricsForSample(g_state, gyro_mag, jerk_proxy, is_stable, frame.is_occluded,
                              frame.occlusion_pct, g_tilt_deg_current);

  updateStateMachine(frame, imu_stable);
  updateLiveIssue(g_state, frame, is_stable, gyro_mag, jerk_proxy);
  maybePrintLiveFeedback(now, frame, is_stable, gyro_mag, jerk_proxy);

  if (tryDockCompleteSerial(serial_d)) {
    transitionTo(TrialState::Complete, "DOCK_COMPLETE");
    digitalWrite(STATUS_LED_PIN, HIGH);
    processAllPendingEvents(now);
  }

  if (g_stream_raw_csv) {
    emitCsvRow(now, frame, ax, ay, az, gx, gy, gz, acc_mag, gyro_mag, jerk_proxy, is_stable);
  }

  processAllPendingEvents(now);
}
