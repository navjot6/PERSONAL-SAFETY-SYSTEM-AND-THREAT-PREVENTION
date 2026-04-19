import time
import math
from dataclasses import dataclass
from collections import deque

import cv2
import mediapipe as mp

@dataclass
class ThreatEvent:
    message: str
    risk_score: float

class ThreatDetector:
    def __init__(self, threshold: float = 0.72, cooldown_seconds: int = 45):
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self.monitoring = False
        self.model_name = "MediaPipe Pose (Edge AI)"

        self.risk_score = 0.0
        self.last_alert_time = 0.0
        self.last_message = "No alerts yet"
        self.total_alerts = 0
        self.camera_open = False

        self._distress_history = deque(maxlen=10)
        self._history_required_ratio = 0.25

        self._risk_ema_alpha = 0.18
        self._arm_raise_margin = 0.0      
        self._head_raise_margin = 0.015  
        self._elbow_extended_deg = 130.0

        self._motion_threshold = 0.015
        self._prev_points = None
        self._motion_score = 0.0
        
        self._prev_gray = None
        self._global_motion_score = 0.0
        self._global_motion_threshold = 0.35  

        self._alert_hold_seconds = 7
        self._alert_hold_until = 0.0

        self.mp_pose = mp.solutions.pose
        self.pose = self.mp_pose.Pose()
        self.mp_draw = mp.solutions.drawing_utils

    def set_monitoring(self, value: bool):
        if self.monitoring and not value:
            self.risk_score = 0.0
        self.monitoring = value

    def set_camera_open(self, value: bool):
        self.camera_open = value

    def _cooldown_active(self) -> bool:
        return (time.time() - self.last_alert_time) < self.cooldown_seconds

    def _get_point(self, lm, landmark):
        p = lm[landmark]
        return (float(p.x), float(p.y), float(p.z))

    def _angle_at_elbow(self, shoulder, elbow, wrist) -> float:
        sx, sy, _ = shoulder
        ex, ey, _ = elbow
        wx, wy, _ = wrist

        v1x, v1y = sx - ex, sy - ey
        v2x, v2y = wx - ex, wy - ey
        v1_norm = math.hypot(v1x, v1y)
        v2_norm = math.hypot(v2x, v2y)
        if v1_norm < 1e-6 or v2_norm < 1e-6:
            return 0.0

        dot = (v1x * v2x + v1y * v2y) / (v1_norm * v2_norm)
        dot = max(-1.0, min(1.0, dot))
        ang = math.degrees(math.acos(dot))
        return ang

    def _point_distance_xy(self, a, b) -> float:
        ax, ay, _ = a
        bx, by, _ = b
        return math.hypot(ax - bx, ay - by)

    def process_frame(self, frame):
        event = None

        if not self.monitoring:
            return frame, event

        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        small = cv2.resize(gray, (64, 36))
        if self._prev_gray is not None and self._prev_gray.shape == small.shape:
            diff = cv2.absdiff(small, self._prev_gray)
            mean_diff = float(diff.mean())  # 0..255
            # Normalize to 0..1 range for scoring.
            self._global_motion_score = max(0.0, min(1.0, mean_diff / 40.0))
        else:
            self._global_motion_score = 0.0
        self._prev_gray = small

        results = self.pose.process(rgb)

        target_risk = 0.0
        distress_condition = False
        details = {}

        if results.pose_landmarks:
            lm = results.pose_landmarks.landmark

            nose = self._get_point(lm, self.mp_pose.PoseLandmark.NOSE)
            le = self._get_point(lm, self.mp_pose.PoseLandmark.LEFT_EYE)
            re = self._get_point(lm, self.mp_pose.PoseLandmark.RIGHT_EYE)
            ear_l = self._get_point(lm, self.mp_pose.PoseLandmark.LEFT_EAR)
            ear_r = self._get_point(lm, self.mp_pose.PoseLandmark.RIGHT_EAR)

            lw = self._get_point(lm, self.mp_pose.PoseLandmark.LEFT_WRIST)
            rw = self._get_point(lm, self.mp_pose.PoseLandmark.RIGHT_WRIST)
            ls = self._get_point(lm, self.mp_pose.PoseLandmark.LEFT_SHOULDER)
            rs = self._get_point(lm, self.mp_pose.PoseLandmark.RIGHT_SHOULDER)
            lelb = self._get_point(lm, self.mp_pose.PoseLandmark.LEFT_ELBOW)
            relb = self._get_point(lm, self.mp_pose.PoseLandmark.RIGHT_ELBOW)

            shoulder_y = (ls[1] + rs[1]) / 2.0
            head_top_y = min(nose[1], le[1], re[1], ear_l[1], ear_r[1])

            left_arm_raised = lw[1] < (ls[1] - self._arm_raise_margin)
            right_arm_raised = rw[1] < (rs[1] - self._arm_raise_margin)
            hands_high = (lw[1] < (head_top_y - self._head_raise_margin)) and (
                rw[1] < (head_top_y - self._head_raise_margin)
            )
            one_arm_raised = left_arm_raised ^ right_arm_raised

            left_elbow_angle = self._angle_at_elbow(ls, lelb, lw)
            right_elbow_angle = self._angle_at_elbow(rs, relb, rw)
            left_extended = left_elbow_angle >= self._elbow_extended_deg
            right_extended = right_elbow_angle >= self._elbow_extended_deg
            both_extended = left_extended and right_extended

            if self._prev_points is not None:
                nose_move = self._point_distance_xy(nose, self._prev_points["nose"])
                lw_move = self._point_distance_xy(lw, self._prev_points["lw"])
                rw_move = self._point_distance_xy(rw, self._prev_points["rw"])
                self._motion_score = 0.5 * nose_move + 0.25 * lw_move + 0.25 * rw_move
            else:
                self._motion_score = 0.0

            panic_motion = self._motion_score >= self._motion_threshold

            self._prev_points = {"nose": nose, "lw": lw, "rw": rw}

            if one_arm_raised:
                target_risk = max(target_risk, 0.35)
            if left_arm_raised and right_arm_raised:
                target_risk = max(target_risk, 0.7)
            if hands_high:
                target_risk = max(target_risk, 0.9)
            if hands_high and both_extended:
                target_risk = max(target_risk, 0.92)

            if target_risk > 0 and panic_motion:
                target_risk = min(1.0, target_risk + 0.12)

            distress_condition = bool(
                hands_high
                or (panic_motion and (left_arm_raised or right_arm_raised))
                or (panic_motion and self._global_motion_score >= self._global_motion_threshold)
            )
            details = {
                "hands_high": hands_high,
                "both_extended": both_extended,
                "panic_motion": panic_motion,
                "motion_score": round(self._motion_score, 4),
                "elbow_angles": (round(left_elbow_angle, 1), round(right_elbow_angle, 1)),
                "shoulder_y": round(shoulder_y, 4),
                "head_top_y": round(head_top_y, 4),
            }
            self.mp_draw.draw_landmarks(
                frame,
                results.pose_landmarks,
                self.mp_pose.POSE_CONNECTIONS,
            )
        if self._global_motion_score >= self._global_motion_threshold and target_risk < 0.6:
            target_risk = max(target_risk, 0.6)
            distress_condition = True

        if distress_condition or target_risk > 0:
            self.risk_score = (1.0 - self._risk_ema_alpha) * self.risk_score + self._risk_ema_alpha * target_risk
        else:
            self.risk_score = max(0.0, self.risk_score * 0.82)

        self.risk_score = max(0.0, min(1.0, self.risk_score))

        self._distress_history.append(distress_condition)
        if self._distress_history:
            distress_ratio = sum(self._distress_history) / len(self._distress_history)
        else:
            distress_ratio = 0.0

        now = time.time()
        if now < self._alert_hold_until:
            self.risk_score = max(self.risk_score, 0.72)

        if (
            self.risk_score >= self.threshold
            and distress_ratio >= self._history_required_ratio
            and not self._cooldown_active()
        ):
            self.last_alert_time = now
            self.total_alerts += 1
            self._alert_hold_until = now + self._alert_hold_seconds

            if results.pose_landmarks and details.get("panic_motion"):
                self.last_message = "⚠️ Possible distress gesture + sudden movement!"
            elif results.pose_landmarks and details.get("hands_high") and details.get("both_extended"):
                self.last_message = "🚨 Hands-up distress posture detected!"
            elif results.pose_landmarks and details.get("hands_high"):
                self.last_message = "⚠️ Suspicious hands-up posture detected!"
            else:
                self.last_message = "⚠️ Suspicious posture detected!"

            event = {
                "message": self.last_message,
                "risk_score": round(self.risk_score, 3),
            }
            self.risk_score = 1.0

        self._annotate(frame)
        return frame, event

    def _annotate(self, frame):
        status = "ACTIVE" if self.monitoring else "STOPPED"
        distress_ratio = sum(self._distress_history) / len(self._distress_history) if self._distress_history else 0.0
        cooldown_left = max(
            0, int(self.cooldown_seconds - (time.time() - self.last_alert_time))
        )
        cv2.putText(frame, f"AI: {self.model_name}", (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        cv2.putText(frame, f"Monitoring: {status}", (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        cv2.putText(frame, f"Risk: {self.risk_score:.2f}", (10, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)

        cv2.putText(frame, f"Threat conf: {distress_ratio:.2f}", (10, 120),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 165, 0), 2)

        cv2.putText(frame, f"Cooldown: {cooldown_left}s", (10, 100),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    def get_status(self):
        cooldown_left = max(
            0, int(self.cooldown_seconds - (time.time() - self.last_alert_time))
        )

        distress_ratio = sum(self._distress_history) / len(self._distress_history) if self._distress_history else 0.0

        return {
            "monitoring": self.monitoring,
            "model": self.model_name,
            "model_loaded": True,
            "risk_score": round(self.risk_score, 3),
            "threshold": self.threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "cooldown_remaining": cooldown_left,
            "last_message": self.last_message,
            "total_alerts": self.total_alerts,
            "camera_status": "active" if self.camera_open else "disconnected",
            "threat_confidence": round(distress_ratio, 3),
        }
