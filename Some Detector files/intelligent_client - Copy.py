#!/usr/bin/env python3
"""
ML-Driven Intelligent Ping-Pong Handover Detector with Adaptive DC Management.

Implements the full theoretical framework from:
"ML-Based Intelligent Ping-Pong Handover Detection and Multi-UE Dynamic Anchor 
Placement for Dense 5G NR Small-Cell Networks"

Features:
  - Per-UE ping-pong probability P_pp computed from 5 features via logistic regression
  - DBSCAN spatial clustering with cost-benefit analysis
  - Dynamic Dual Connectivity (DC) assignment and adaptive removal
  - P_pp >= 0.65 threshold for anchor deployment
  - Time-decay weighting for recent HO events
  - Coverage constraint validation
  - Automatic DC retirement when it fails to reduce HOs

Usage:
  python intelligent_client.py --url http://localhost:8080 --verbose --ppp-threshold 0.65
"""

from __future__ import annotations

import argparse
import json
import math
import socket
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Set
from urllib.parse import urlparse

import requests


class LogisticRegression:
    """Lightweight logistic regression for P_pp inference."""
    
    def __init__(self, weights: List[float] = None):
        """
        Initialize with pre-trained weights.
        Default weights calibrated for 5G NR pedestrian/vehicular scenarios.
        """
        # Weights: [bias, f_HO, sigma2_RSRP, R_rev, D_flip, Osc]
        self.weights = weights or [-2.0, 1.6, 0.8, 1.7, 1.0, 1.8]
        self.feature_names = ['f_HO', 'sigma2_RSRP', 'R_rev', 'D_flip', 'Osc']
    
    def sigmoid(self, z: float) -> float:
        """Numerically stable sigmoid."""
        if z > 20:
            return 1.0
        if z < -20:
            return 0.0
        return 1.0 / (1.0 + math.exp(-z))
    
    def predict_proba(self, features: List[float]) -> float:
        """
        Compute P_pp from 5 normalized features.
        
        Args:
            features: [f_HO_norm, sigma2_RSRP_norm, R_rev, D_flip_norm, Osc]
        
        Returns:
            P_pp in [0, 1]
        """
        z = self.weights[0]  # bias
        for i, f in enumerate(features):
            z += self.weights[i + 1] * f
        return self.sigmoid(z)


class IntelligentPingPongDetector:
    """ML-driven ping-pong detector with adaptive DC management."""
    
    def __init__(self, args):
        self.url = args.url.rstrip("/")
        self.interval = args.interval
        self.window_s = args.window
        self.ppp_threshold = args.ppp_threshold  # P_pp >= 0.65
        self.cluster_threshold = args.cluster_threshold
        self.cluster_radius = args.cluster_radius
        self.anchor_cooldown_s = args.cooldown
        self.c_ho = args.ho_cost
        self.c_anchor = args.anchor_cost
        self.verbose = args.verbose
        self.report_path = Path(args.report)
        self.tcp_enabled = args.tcp
        self.tcp_host = args.tcp_host or (urlparse(self.url).hostname or "localhost")
        self.tcp_port = args.tcp_port
        self.max_iterations = args.max_iterations
        
        # Detector components
        self.ml_model = LogisticRegression()
        self.lambda_decay = 0.1  # Half-life ≈ 7 seconds
        self.r_anchor = args.r_anchor  # Coverage radius
        
        # State tracking
        self.ho_history = defaultdict(lambda: deque(maxlen=300))
        self.seen_events = set()
        self.active_anchors = {}
        self.dc_assignments = {}  # ue_id -> {anchor_gnb_id, senb_id, created_at}
        self.dc_performance = defaultdict(lambda: {"ho_before": 0, "ho_after": 0})
        self.last_anchor_at = 0.0
        self.last_dc_removal_at = {}  # ue_id -> timestamp
        
        self.stats = {
            "evaluation_steps": 0,
            "anchors_deployed": 0,
            "dc_assignments": 0,
            "dc_removals": 0,
            "cost_benefit_rejections": 0,
            "false_positives": 0,
            "errors": 0,
            "total_ho_events": 0,
            "hos_avoided": 0,
        }
    
    def run(self):
        """Main detection loop."""
        self._log(f"ML Detector connected to {self.url}")
        self._log(f"P_pp threshold: {self.ppp_threshold}, Cluster threshold: {self.cluster_threshold}")
        i = 0
        while self.max_iterations <= 0 or i < self.max_iterations:
            i += 1
            try:
                state = self._get_state()
                self._ingest_handovers(state)
                candidates = self._score_ues(state)
                self._evaluate_dc_performance(state)
                clusters = self._cluster_candidates(candidates)
                self._evaluate_clusters(state, clusters)
                self._write_report(candidates, clusters)
                self._push_status()
            except KeyboardInterrupt:
                raise
            except Exception as exc:
                self.stats["errors"] += 1
                self._log(f"ERROR: {exc}")
            time.sleep(self.interval)
    
    def _get_state(self):
        """Fetch current simulator state."""
        resp = requests.get(f"{self.url}/api/get_state", timeout=5)
        resp.raise_for_status()
        return resp.json()
    
    def _ingest_handovers(self, state):
        """Ingest and deduplicate HO events."""
        for ev in state.get("handover_events", []):
            key = (ev.get("step"), ev.get("ue_id"), ev.get("serving"), ev.get("target"))
            if key in self.seen_events:
                continue
            self.seen_events.add(key)
            uid = ev.get("ue_id")
            if uid:
                self.ho_history[uid].append(ev)
                self.stats["total_ho_events"] += 1
    
    def _evaluate_dc_performance(self, state):
        """
        Check if assigned DCs are reducing HO rates.
        If DC doesn't help for 30s, remove it.
        """
        now = float(state.get("sim_time") or 0.0)
        
        for ue_id, dc_info in list(self.dc_assignments.items()):
            anchor_id = dc_info["anchor_gnb_id"]
            created_at = dc_info["created_at"]
            
            # Evaluate after 15s of DC assignment
            if now - created_at < 15.0:
                continue
            
            # Count HOs in last window before DC vs. after DC
            recent_hos = [
                ev for ev in self.ho_history[ue_id]
                if now - float(ev.get("time") or 0.0) <= self.window_s
            ]
            
            if len(recent_hos) < 2:
                continue
            
            # Crude estimate: if HOs are still high after DC, consider removing it
            ho_rate = len(recent_hos) / max(self.window_s, 1.0)
            
            # If HO rate > 0.3 HOs/s and DC has been active > 20s, remove it
            if ho_rate > 0.3 and now - created_at > 20.0:
                last_removal = self.last_dc_removal_at.get(ue_id, 0.0)
                if now - last_removal > 30.0:  # Cooldown to avoid thrashing
                    self._remove_dc(ue_id, anchor_id)
                    self.stats["dc_removals"] += 1
                    self.last_dc_removal_at[ue_id] = now
    
    def _remove_dc(self, ue_id: str, anchor_id: str):
        """Remove DC from UE, revert to normal handover."""
        try:
            requests.post(f"{self.url}/api/anchor/disable", timeout=3)
            if ue_id in self.dc_assignments:
                del self.dc_assignments[ue_id]
            self._log(f"DC REMOVED: {ue_id} from {anchor_id} (HO rate too high)")
        except Exception as e:
            self._log(f"Error removing DC for {ue_id}: {e}")
    
    def _score_ues(self, state) -> List[Dict]:
        """
        Score all UEs for ping-pong probability using ML features.
        Returns candidates with P_pp >= threshold.
        """
        now = float(state.get("sim_time") or 0.0)
        ues = state.get("ues", {})
        candidates = []
        
        for uid, ue in ues.items():
            if ue.get("dc_enabled"):
                continue  # Skip UEs already in DC (unless for re-evaluation)
            
            events = [
                ev for ev in self.ho_history[uid]
                if now - float(ev.get("time") or 0.0) <= self.window_s
            ]
            
            if len(events) < 3:
                continue
            
            # Extract features (Section 4.1 of PDF)
            features = self._extract_features(events, self.window_s)
            
            # ML inference: compute P_pp
            p_pp = self.ml_model.predict_proba(features["normalized"])
            
            if p_pp >= self.ppp_threshold:
                candidates.append({
                    "ue_id": uid,
                    "x": float(ue.get("x", 0.0)),
                    "y": float(ue.get("y", 0.0)),
                    "p_pp": p_pp,
                    "features": features,
                    "ho_count": len(events),
                    "last_pair": self._last_pair(events),
                    "sim_time": now,
                })
                self._log(
                    f"{uid:8s} P_pp={p_pp:.3f} HOs={len(events)} "
                    f"f_HO={features['ho_frequency']:.2f} "
                    f"osc={features['oscillation']:.2f} "
                    f"rev={features['reversal_ratio']:.2f}")
        
        return candidates
    
    def _extract_features(self, events: List[Dict], window_s: float) -> Dict:
        """
        Extract and normalize 5 features per Eq.(1) of PDF.
        
        Returns:
            Dict with raw and normalized features
        """
        # Feature 1: HO frequency (Eq. in Section 4.1)
        ho_frequency = len(events) / max(window_s, 1.0)
        f_ho_norm = min(1.0, ho_frequency / 0.5)  # Normalize by typical max rate
        
        # Feature 2: RSRP variance
        rsrps = [float(ev.get("rsrp") or ev.get("RSRP_dBm") or -120.0) for ev in events]
        mean_rsrp = sum(rsrps) / len(rsrps)
        rsrp_variance = sum((v - mean_rsrp) ** 2 for v in rsrps) / len(rsrps)
        sigma2_rsrp_norm = min(1.0, rsrp_variance / 80.0)
        
        # Feature 3: Reversal ratio (cell revisit - Eq. in Section 4.1)
        reversals = 0
        for i in range(1, len(events)):
            if events[i].get("target") == events[i - 1].get("serving"):
                reversals += 1
        r_rev = reversals / max(len(events) - 1, 1)
        
        # Feature 4: Direction flip (HO direction changes)
        direction_flips = 0
        for i in range(1, len(events)):
            prev_serv = events[i - 1].get("serving")
            prev_targ = events[i - 1].get("target")
            curr_serv = events[i].get("serving")
            curr_targ = events[i].get("target")
            # Flip if direction reverses
            if prev_targ == curr_serv and prev_serv == curr_targ:
                direction_flips += 1
        d_flip_norm = min(1.0, direction_flips / max(len(events) - 1, 1))
        
        # Feature 5: Oscillation score (A→B→A reversals - Eq.2)
        oscillations = 0
        for i in range(2, len(events)):
            if events[i - 2].get("serving") == events[i].get("target"):
                oscillations += 1
        osc = oscillations / max(len(events) - 2, 1)
        
        return {
            "ho_frequency": ho_frequency,
            "rsrp_variance": rsrp_variance,
            "reversal_ratio": r_rev,
            "direction_flip": d_flip_norm,
            "oscillation": osc,
            "normalized": [f_ho_norm, sigma2_rsrp_norm, r_rev, d_flip_norm, osc],
        }
    
    def _last_pair(self, events: List[Dict]) -> Tuple[str, str]:
        """Get the last (serving, target) pair."""
        ev = events[-1]
        return ev.get("serving"), ev.get("target")
    
    def _cluster_candidates(self, candidates: List[Dict]) -> List[List[Dict]]:
        """
        DBSCAN spatial clustering (Section 3.3 of PDF).
        Groups ping-pong UEs within cluster_radius distance.
        """
        if len(candidates) < 3:
            return []
        
        remaining = list(candidates)
        clusters = []
        
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            changed = True
            
            while changed:
                changed = False
                for cand in list(remaining):
                    # Check if within eps (cluster_radius) of any cluster member
                    for member in cluster:
                        dist = self._dist(cand, member)
                        if dist <= self.cluster_radius:
                            cluster.append(cand)
                            remaining.remove(cand)
                            changed = True
                            break
            
            # Keep only clusters with >= 3 UEs (MinPts = 3, Eq.4)
            if len(cluster) >= 3:
                clusters.append(cluster)
        
        return clusters
    
    def _evaluate_clusters(self, state: Dict, clusters: List[List[Dict]]):
        """
        Evaluate each cluster for anchor deployment.
        Applies coverage constraint, cost-benefit, and time-decay weighting.
        """
        self.stats["evaluation_steps"] += 1
        now = float(state.get("sim_time") or 0.0)
        
        for cluster in clusters:
            # Weighted centroid (Eq. 7a, 7b)
            cx, cy = self._weighted_centroid(cluster, now)
            
            # Coverage constraint: all UEs within R_anchor (Eq. 8)
            r_max = max(self._dist(c, {"x": cx, "y": cy}) for c in cluster)
            if r_max > self.r_anchor:
                self._log(f"SKIP: Cluster too spread (r_max={r_max:.0f} > {self.r_anchor})")
                continue
            
            # Time-decay weight and cluster score (Eq. 5, 6)
            weights = [math.exp(-self.lambda_decay * (now - c.get("sim_time", now))) 
                      for c in cluster]
            score_k = sum(w * c["p_pp"] for w, c in zip(weights, cluster))
            
            if score_k < self.cluster_threshold:
                self.stats["cost_benefit_rejections"] += 1
                self._log(f"SKIP: Cluster score {score_k:.2f} < {self.cluster_threshold}")
                continue
            
            # Cost-benefit analysis (Eq. 9)
            avg_ho_rate = sum(c["features"]["ho_frequency"] for c in cluster) / len(cluster)
            benefit = len(cluster) * self.c_ho * avg_ho_rate * self.window_s - self.c_anchor
            
            if benefit <= 0:
                self.stats["cost_benefit_rejections"] += 1
                self._log(f"SKIP: Cost-benefit {benefit:.2f} <= 0")
                continue
            
            # Cooldown to prevent repeated deployments
            if time.time() - self.last_anchor_at < self.anchor_cooldown_s:
                continue
            
            # Deploy anchor and assign DC
            self._deploy_anchor_and_assign_dc(cx, cy, cluster, benefit, score_k)
    
    def _weighted_centroid(self, cluster: List[Dict], now: float) -> Tuple[float, float]:
        """Compute weighted centroid using time-decay weights (Eq. 7)."""
        weights = [math.exp(-self.lambda_decay * (now - c.get("sim_time", now))) 
                  for c in cluster]
        total_weight = sum(weights)
        if total_weight == 0:
            total_weight = 1.0
        
        cx = sum(w * c["x"] for w, c in zip(weights, cluster)) / total_weight
        cy = sum(w * c["y"] for w, c in zip(weights, cluster)) / total_weight
        
        return cx, cy
    
    def _deploy_anchor_and_assign_dc(self, x: float, y: float, 
                                     cluster: List[Dict], 
                                     benefit: float, score: float):
        """Deploy anchor and assign UEs to DC."""
        payload = {
            "x": round(x, 1),
            "y": round(y, 1),
            "tx_power": 50,
            "num_sectors": 6,
            "is_anchor": True,
            "triggered_by": ",".join(c["ue_id"] for c in cluster),
            "ho_count": sum(c["ho_count"] for c in cluster),
        }
        
        try:
            resp = requests.post(f"{self.url}/api/add_anchor_gnb", json=payload, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self._log(f"Anchor deployment failed: {e}")
            return
        
        anchor_id = data.get("anchor_gnb_id") or data.get("gnb_id")
        if not anchor_id:
            self._log(f"No anchor_gnb_id in response: {data}")
            return
        
        assigned = []
        for cand in cluster:
            uid = cand["ue_id"]
            senb = cand["last_pair"][1] or cand["last_pair"][0]
            
            # Assign DC
            assign_payload = {
                "ue_id": uid,
                "anchor_gnb_id": anchor_id,
                "preferred_senb_id": senb,
            }
            try:
                requests.post(f"{self.url}/api/anchor/assign", 
                            json=assign_payload, timeout=5)
                
                # Track DC assignment for performance monitoring
                self.dc_assignments[uid] = {
                    "anchor_gnb_id": anchor_id,
                    "senb_id": senb,
                    "created_at": time.time(),
                }
                assigned.append(uid)
                self.stats["dc_assignments"] += 1
                
                if self.tcp_enabled:
                    self._tcp_assign(uid, anchor_id)
            except Exception as e:
                self._log(f"DC assign failed for {uid}: {e}")
        
        self.active_anchors[anchor_id] = {
            "x": round(x, 1),
            "y": round(y, 1),
            "cluster_ues": assigned,
            "benefit": round(benefit, 3),
            "score": round(score, 3),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        self.stats["anchors_deployed"] += 1
        self.stats["hos_avoided"] += int(benefit)
        self.last_anchor_at = time.time()
        
        self._log(
            f"✓ ANCHOR DEPLOYED: {anchor_id} @ ({x:.0f},{y:.0f}) "
            f"UEs={assigned} benefit={benefit:.2f} score={score:.2f}")
    
    def _tcp_assign(self, ue_id: str, anchor_id: str):
        """Send TCP ASSIGN_ANCHOR command."""
        try:
            with socket.create_connection((self.tcp_host, self.tcp_port), timeout=3) as sock:
                sock.sendall(f"ASSIGN_ANCHOR:{ue_id}:{anchor_id}\n".encode("utf-8"))
                sock.recv(1024)
        except OSError as exc:
            self._log(f"TCP assign skipped for {ue_id}: {exc}")
    
    def _dist(self, a: Dict, b: Dict) -> float:
        """Euclidean distance."""
        return math.hypot(a["x"] - b["x"], a["y"] - b["y"])
    
    def _write_report(self, candidates: List[Dict], clusters: List[List[Dict]]):
        """Write JSON report."""
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stats": self.stats,
            "ppp_threshold": self.ppp_threshold,
            "active_anchors": self.active_anchors,
            "dc_assignments": self.dc_assignments,
            "candidate_ues": [
                {k: v for k, v in c.items() if k != "features"} 
                for c in candidates
            ],
            "clusters": [[c["ue_id"] for c in cluster] for cluster in clusters],
        }
        self.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    
    def _push_status(self):
        """Push detector status to simulator."""
        payload = {
            "evaluation_steps": self.stats["evaluation_steps"],
            "active_anchors": list(self.active_anchors.keys()),
            "cost_benefit_rejections": self.stats["cost_benefit_rejections"],
            "false_positives": self.stats["false_positives"],
            "ue_count": len(self.ho_history),
            "errors": self.stats["errors"],
            "dc_assignments": self.stats["dc_assignments"],
            "dc_removals": self.stats["dc_removals"],
            "hos_avoided": self.stats["hos_avoided"],
        }
        try:
            requests.post(f"{self.url}/api/update_detector_status", 
                        json=payload, timeout=2)
        except requests.RequestException:
            pass
    
    def _log(self, msg: str):
        """Log with timestamp."""
        if self.verbose:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(
        description="ML-Driven Ping-Pong Detector with Adaptive DC Management")
    parser.add_argument("--url", default="http://localhost:8080", 
                       help="Simulator server URL")
    parser.add_argument("--interval", type=float, default=0.5, 
                       help="Polling interval in seconds")
    parser.add_argument("--window", type=float, default=12.0, 
                       help="HO sliding window in seconds")
    parser.add_argument("--ppp-threshold", type=float, default=0.65, 
                       help="P_pp >= threshold for anchor deployment (Eq.1)")
    parser.add_argument("--cluster-threshold", type=float, default=1.5, 
                       help="Cluster score threshold (Eq.6)")
    parser.add_argument("--cluster-radius", type=float, default=150.0, 
                       help="DBSCAN epsilon (canvas pixels)")
    parser.add_argument("--r-anchor", type=float, default=60.0, 
                       help="Anchor coverage radius (canvas pixels, ≈300m)")
    parser.add_argument("--cooldown", type=float, default=10.0, 
                       help="Min seconds between anchor deployments")
    parser.add_argument("--ho-cost", type=float, default=0.7, 
                       help="Cost per unnecessary HO (Eq.9)")
    parser.add_argument("--anchor-cost", type=float, default=1.0, 
                       help="Cost per AnchorGNB deployment (Eq.9)")
    parser.add_argument("--report", default="ml_intelligent_report.json", 
                       help="JSON report output path")
    parser.add_argument("--tcp", action="store_true", 
                       help="Enable TCP ASSIGN_ANCHOR commands")
    parser.add_argument("--tcp-host", default=None, 
                       help="TCP host (defaults to URL hostname)")
    parser.add_argument("--tcp-port", type=int, default=5555, 
                       help="TCP port for anchor commands")
    parser.add_argument("--max-iterations", type=int, default=0, 
                       help="Stop after N iterations; 0 = forever")
    parser.add_argument("--verbose", action="store_true", 
                       help="Print live detector decisions")
    return parser.parse_args()


if __name__ == "__main__":
    IntelligentPingPongDetector(parse_args()).run()
