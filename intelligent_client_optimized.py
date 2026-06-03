#!/usr/bin/env python3
"""
OPTIMIZED ML-Driven Intelligent Ping-Pong Detector with Smart DC Assignment.

Improvements over original:
  - SMART DC ASSIGNMENT: Only assign anchor if RSRP > nearest gNB
  - MULTI-ANCHOR SUPPORT: Deploy separate anchors for different clusters
  - RSRP-AWARE ASSIGNMENT: Skip UEs far from anchor, keep with nearby gNBs
  - MAXIMUM SINR RETENTION: Don't degrade signal for ping-pong UEs
  - THROUGHPUT OPTIMIZATION: Focus HO reduction on critical paths

Usage:
  python intelligent_client_optimized.py --url http://localhost:8080 --verbose
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
        """Initialize with pre-trained weights."""
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
        """Compute P_pp from 5 normalized features."""
        z = self.weights[0]
        for i, f in enumerate(features):
            z += self.weights[i + 1] * f
        return self.sigmoid(z)


class OptimizedIntelligentDetector:
    """Optimized detector with smart RSRP-based DC assignment."""
    
    def __init__(self, args):
        self.url = args.url.rstrip("/")
        self.interval = args.interval
        self.window_s = args.window
        self.ppp_threshold = args.ppp_threshold
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
        
        # Optimized parameters
        self.rsrp_threshold_improvement = args.rsrp_improvement  # Min dB gain to assign
        self.min_distance_to_anchor = args.min_dist_anchor  # Skip if too far
        
        self.ml_model = LogisticRegression()
        self.lambda_decay = 0.1
        self.r_anchor = args.r_anchor
        
        # State tracking
        self.ho_history = defaultdict(lambda: deque(maxlen=300))
        self.seen_events = set()
        self.active_anchors = {}
        self.dc_assignments = {}
        self.last_anchor_at = 0.0
        
        self.stats = {
            "evaluation_steps": 0,
            "anchors_deployed": 0,
            "dc_assignments": 0,
            "dc_smart_skipped": 0,  # UEs skipped due to better gNB
            "cost_benefit_rejections": 0,
            "errors": 0,
            "total_ho_events": 0,
            "hos_avoided": 0,
        }
    
    def run(self):
        """Main detection loop."""
        self._log(f"✓ OPTIMIZED Detector started (Smart RSRP-based assignment)")
        self._log(f"  RSRP improvement threshold: {self.rsrp_threshold_improvement:.1f} dB")
        self._log(f"  Max distance to anchor: {self.min_distance_to_anchor:.0f} pixels")
        self._log(f"  P_pp threshold: {self.ppp_threshold}, Cluster threshold: {self.cluster_threshold}")
        
        i = 0
        while self.max_iterations <= 0 or i < self.max_iterations:
            i += 1
            try:
                state = self._get_state()
                self._ingest_handovers(state)
                candidates = self._score_ues(state)
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
    
    def _score_ues(self, state) -> List[Dict]:
        """Score all UEs for ping-pong probability."""
        now = float(state.get("sim_time") or 0.0)
        ues = state.get("ues", {})
        candidates = []
        
        for uid, ue in ues.items():
            if ue.get("dc_enabled"):
                continue
            
            events = [
                ev for ev in self.ho_history[uid]
                if now - float(ev.get("time") or 0.0) <= self.window_s
            ]
            
            if len(events) < 3:
                continue
            
            features = self._extract_features(events, self.window_s)
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
                    "current_rsrp": float(ue.get("rsrp") or -120.0),
                })
                self._log(
                    f"{uid:8s} P_pp={p_pp:.3f} HOs={len(events)} "
                    f"RSRP={ue.get('rsrp', 'N/A')} "
                    f"f_HO={features['ho_frequency']:.2f}")
        
        return candidates
    
    def _extract_features(self, events: List[Dict], window_s: float) -> Dict:
        """Extract 5 ML features."""
        ho_frequency = len(events) / max(window_s, 1.0)
        f_ho_norm = min(1.0, ho_frequency / 0.5)
        
        rsrps = [float(ev.get("rsrp") or ev.get("RSRP_dBm") or -120.0) for ev in events]
        mean_rsrp = sum(rsrps) / len(rsrps)
        rsrp_variance = sum((v - mean_rsrp) ** 2 for v in rsrps) / len(rsrps)
        sigma2_rsrp_norm = min(1.0, rsrp_variance / 80.0)
        
        reversals = 0
        for i in range(1, len(events)):
            if events[i].get("target") == events[i - 1].get("serving"):
                reversals += 1
        r_rev = reversals / max(len(events) - 1, 1)
        
        direction_flips = 0
        for i in range(1, len(events)):
            prev_serv = events[i - 1].get("serving")
            prev_targ = events[i - 1].get("target")
            curr_serv = events[i].get("serving")
            curr_targ = events[i].get("target")
            if prev_targ == curr_serv and prev_serv == curr_targ:
                direction_flips += 1
        d_flip_norm = min(1.0, direction_flips / max(len(events) - 1, 1))
        
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
        """DBSCAN spatial clustering."""
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
                    for member in cluster:
                        dist = self._dist(cand, member)
                        if dist <= self.cluster_radius:
                            cluster.append(cand)
                            remaining.remove(cand)
                            changed = True
                            break
            
            if len(cluster) >= 3:
                clusters.append(cluster)
        
        return clusters
    
    def _evaluate_clusters(self, state: Dict, clusters: List[List[Dict]]):
        """Evaluate clusters and deploy anchors intelligently."""
        self.stats["evaluation_steps"] += 1
        now = float(state.get("sim_time") or 0.0)
        
        for cluster_idx, cluster in enumerate(clusters):
            # Compute optimized anchor position
            cx, cy = self._weighted_centroid(cluster, now)
            cx, cy = self._optimize_anchor_position((cx, cy), cluster)
            
            # Coverage constraint
            r_max = max(self._dist(c, {"x": cx, "y": cy}) for c in cluster)
            if r_max > self.r_anchor:
                self._log(f"SKIP Cluster {cluster_idx}: too spread (r_max={r_max:.0f})")
                continue
            
            # Cluster score
            weights = [math.exp(-self.lambda_decay * (now - c.get("sim_time", now))) 
                      for c in cluster]
            score_k = sum(w * c["p_pp"] for w, c in zip(weights, cluster))
            
            if score_k < self.cluster_threshold:
                self.stats["cost_benefit_rejections"] += 1
                continue
            
            # Cost-benefit
            avg_ho_rate = sum(c["features"]["ho_frequency"] for c in cluster) / len(cluster)
            benefit = len(cluster) * self.c_ho * avg_ho_rate * self.window_s - self.c_anchor
            
            if benefit <= 0:
                self.stats["cost_benefit_rejections"] += 1
                continue
            
            if time.time() - self.last_anchor_at < self.anchor_cooldown_s:
                continue
            
            # Deploy anchor and SMART assign DC
            self._deploy_anchor_and_smart_assign(cx, cy, cluster, benefit, score_k, state)
    
    def _weighted_centroid(self, cluster: List[Dict], now: float) -> Tuple[float, float]:
        """Compute weighted centroid."""
        weights = [math.exp(-self.lambda_decay * (now - c.get("sim_time", now))) 
                  for c in cluster]
        total_weight = sum(weights)
        if total_weight == 0:
            total_weight = 1.0
        
        cx = sum(w * c["x"] for w, c in zip(weights, cluster)) / total_weight
        cy = sum(w * c["y"] for w, c in zip(weights, cluster)) / total_weight
        
        return cx, cy
    
    def _path_loss_estimate(self, anchor_pos: Dict, ue_pos: Dict) -> float:
        """Estimate RSRP using ITU path loss."""
        distance = self._dist(anchor_pos, ue_pos)
        if distance < 1:
            distance = 1.0
        
        path_loss_db = 68.3 + 20 * math.log10(distance) + 32.5
        rsrp = 50 - path_loss_db
        return rsrp
    
    def _optimize_anchor_position(self, centroid: Tuple[float, float], 
                                   cluster: List[Dict]) -> Tuple[float, float]:
        """Grid search for radio-quality optimal position."""
        cx, cy = centroid
        grid_size = 5
        search_radius = self.r_anchor
        
        best_pos = (cx, cy)
        best_min_rsrp = -200
        
        for dx in range(-int(search_radius), int(search_radius) + 1, grid_size):
            for dy in range(-int(search_radius), int(search_radius) + 1, grid_size):
                test_x = cx + dx
                test_y = cy + dy
                test_pos = {"x": test_x, "y": test_y}
                
                min_rsrp = float('inf')
                for ue in cluster:
                    rsrp = self._path_loss_estimate(test_pos, ue)
                    min_rsrp = min(min_rsrp, rsrp)
                
                if min_rsrp > best_min_rsrp:
                    best_min_rsrp = min_rsrp
                    best_pos = (test_x, test_y)
        
        self._log(f"  Optimized pos: ({best_pos[0]:.0f},{best_pos[1]:.0f}) "
                  f"min_RSRP={best_min_rsrp:.1f}dBm")
        return best_pos
    
    def _deploy_anchor_and_smart_assign(self, x: float, y: float, 
                                        cluster: List[Dict], 
                                        benefit: float, score: float,
                                        state: Dict):
        """Deploy anchor and SMART assign DC only to UEs that benefit."""
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
            return
        
        assigned = []
        anchor_pos = {"x": x, "y": y}
        gnbs = state.get("gnbs", {})
        
        for cand in cluster:
            uid = cand["ue_id"]
            ue_pos = {"x": cand["x"], "y": cand["y"]}
            
            # Calculate anchor RSRP
            anchor_rsrp = self._path_loss_estimate(anchor_pos, ue_pos)
            
            # Find nearest gNB and its RSRP
            nearest_gnb_rsrp = -150
            for gnb_id, gnb in gnbs.items():
                if gnb_id == anchor_id:
                    continue
                gnb_pos = {"x": float(gnb.get("x", 0)), "y": float(gnb.get("y", 0))}
                gnb_rsrp = self._path_loss_estimate(gnb_pos, ue_pos)
                nearest_gnb_rsrp = max(nearest_gnb_rsrp, gnb_rsrp)
            
            # Distance check
            dist_to_anchor = self._dist(ue_pos, anchor_pos)
            
            # SMART DECISION: Only assign if conditions met
            rsrp_improvement = anchor_rsrp - nearest_gnb_rsrp
            
            if dist_to_anchor > self.min_distance_to_anchor:
                self._log(f"    {uid}: TOO FAR (dist={dist_to_anchor:.0f}px) → Keep with nearby gNB")
                self.stats["dc_smart_skipped"] += 1
                continue
            
            if rsrp_improvement < self.rsrp_threshold_improvement:
                self._log(f"    {uid}: Poor RSRP gain ({rsrp_improvement:.1f}dB < {self.rsrp_threshold_improvement:.1f}dB) → Skip")
                self.stats["dc_smart_skipped"] += 1
                continue
            
            # UE qualifies for DC
            senb = cand["last_pair"][1] or cand["last_pair"][0]
            assign_payload = {
                "ue_id": uid,
                "anchor_gnb_id": anchor_id,
                "preferred_senb_id": senb,
            }
            
            try:
                requests.post(f"{self.url}/api/anchor/assign", 
                            json=assign_payload, timeout=5)
                self.dc_assignments[uid] = {
                    "anchor_gnb_id": anchor_id,
                    "senb_id": senb,
                    "created_at": time.time(),
                }
                assigned.append(uid)
                self.stats["dc_assignments"] += 1
                self._log(f"    {uid}: ASSIGNED (RSRP gain={rsrp_improvement:.1f}dB) ✓")
            except Exception as e:
                self._log(f"DC assign failed for {uid}: {e}")
        
        if assigned:
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
                f"Assigned={assigned} benefit={benefit:.2f}")
        else:
            self._log(f"✗ ANCHOR {anchor_id} deployed but NO UEs qualified for DC")
    
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
            "ue_count": len(self.ho_history),
            "errors": self.stats["errors"],
            "dc_assignments": self.stats["dc_assignments"],
            "dc_smart_skipped": self.stats["dc_smart_skipped"],
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
        description="OPTIMIZED Ping-Pong Detector with Smart RSRP-Based DC Assignment")
    parser.add_argument("--url", default="http://localhost:8080", 
                       help="Simulator server URL")
    parser.add_argument("--interval", type=float, default=0.5, 
                       help="Polling interval in seconds")
    parser.add_argument("--window", type=float, default=12.0, 
                       help="HO sliding window in seconds")
    parser.add_argument("--ppp-threshold", type=float, default=0.65, 
                       help="P_pp >= threshold for anchor deployment")
    parser.add_argument("--cluster-threshold", type=float, default=1.5, 
                       help="Cluster score threshold")
    parser.add_argument("--cluster-radius", type=float, default=150.0, 
                       help="DBSCAN epsilon (canvas pixels)")
    parser.add_argument("--r-anchor", type=float, default=60.0, 
                       help="Anchor coverage radius (canvas pixels)")
    parser.add_argument("--cooldown", type=float, default=10.0, 
                       help="Min seconds between anchor deployments")
    parser.add_argument("--ho-cost", type=float, default=0.7, 
                       help="Cost per unnecessary HO")
    parser.add_argument("--anchor-cost", type=float, default=1.0, 
                       help="Cost per AnchorGNB deployment")
    
    # OPTIMIZED parameters
    parser.add_argument("--rsrp-improvement", type=float, default=3.0, 
                       help="Min RSRP improvement (dB) to assign DC [3.0]")
    parser.add_argument("--min-dist-anchor", type=float, default=80.0, 
                       help="Max distance to anchor for DC (pixels) [80.0]")
    
    parser.add_argument("--report", default="ml_optimized_report.json", 
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
    OptimizedIntelligentDetector(parse_args()).run()
