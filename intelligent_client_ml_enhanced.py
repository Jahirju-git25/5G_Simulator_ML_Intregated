#!/usr/bin/env python3
"""
ML-ENHANCED Intelligent Ping-Pong Detector with Trained Models & Visualization.

Features:
  - TRAINED MODEL INTEGRATION: Uses pre-trained pingpong_model.pkl + scaler.pkl
  - SMART DC ASSIGNMENT: Only assign anchor if RSRP > nearest gNB
  - VISUAL REPORTS: RSRP plots with HO detection, ping-pong markers, anchor assignment
  - MULTI-ANCHOR SUPPORT: Deploy separate anchors for different clusters
  - RSRP-AWARE ASSIGNMENT: Skip UEs far from anchor, keep with nearby gNBs

Usage:
  python intelligent_client_ml_enhanced.py --url http://localhost:8080 --verbose
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import socket
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Set
from urllib.parse import urlparse

import requests
import numpy as np

# Suppress sklearn feature names warnings
import warnings
warnings.filterwarnings("ignore", category=UserWarning, message=".*feature names.*")
warnings.filterwarnings("ignore", message=".*Trying to unpickle estimator.*")
warnings.filterwarnings("ignore", message=".*InconsistentVersionWarning.*")

try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False

# Matplotlib setup for thread-safe plotting
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    _MATPLOTLIB_OK = True
    _MATPLOTLIB_LOCK = threading.Lock()
except ImportError:
    _MATPLOTLIB_OK = False
    _MATPLOTLIB_LOCK = None


class TrainedPingPongDetector:
    """ML model wrapper for ping-pong probability prediction."""
    
    def __init__(self, model_path: str, scaler_path: str):
        """Load pre-trained sklearn model and scaler."""
        self.model = None
        self.scaler = None
        self.model_loaded = False
        self.scaler_loaded = False
        # Match the exact feature names the model was trained with
        self.feature_names = [
            'f_HO', 'sigma2_RSRP', 'R_rev',
            'D_flip', 'Osc'
        ]
        
        try:
            with open(model_path, 'rb') as f:
                self.model = pickle.load(f)
            self.model_loaded = True
            self._log(f"[OK] ✓ Loaded trained model from {model_path}")
            self._log(f"     Model type: {type(self.model).__name__}")
        except FileNotFoundError:
            self._log(f"[ERROR] Model file not found: {model_path}")
        except Exception as e:
            self._log(f"[ERROR] Failed to load model: {e}")
        
        try:
            with open(scaler_path, 'rb') as f:
                self.scaler = pickle.load(f)
            self.scaler_loaded = True
            self._log(f"[OK] ✓ Loaded scaler from {scaler_path}")
            self._log(f"     Scaler type: {type(self.scaler).__name__}")
        except FileNotFoundError:
            self._log(f"[ERROR] Scaler file not found: {scaler_path}")
        except Exception as e:
            self._log(f"[ERROR] Failed to load scaler: {e}")
    
    def predict_proba(self, features: List[float], ue_id: str = None) -> float:
        """Predict ping-pong probability using trained model."""
        if self.model is None or self.scaler is None:
            return 0.0
        
        try:
            # Scale features and make prediction
            # Pass as 2D array to avoid sklearn warnings
            features_array = np.array([features], dtype=np.float64)
            
            # Check if scaler expects different number of features
            if hasattr(self.scaler, 'n_features_in_'):
                expected_features = self.scaler.n_features_in_
                if len(features) < expected_features:
                    # Pad with zeros for missing features
                    padding = np.zeros((features_array.shape[0], expected_features - len(features)))
                    features_array = np.hstack([features_array, padding])
            
            features_scaled = self.scaler.transform(features_array)
            
            # Predict probability
            proba = self.model.predict_proba(features_scaled)[0][1]
            
            # Log prediction details with UE ID if provided
            if ue_id:
                self._log(f"[PRED] UE {ue_id}: Features={[f'{f:.3f}' for f in features]} → "
                         f"Scaled={[f'{s:.3f}' for s in features_scaled[0][:5]]} → P_pp={proba:.4f}")
            
            return float(proba)
        except Exception as e:
            self._log(f"[ERROR] Prediction error: {e}")
            return 0.0
    
    @staticmethod
    def _log(msg: str):
        """Log message."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] [ModelLoader] {msg}")


class MLEnhancedIntelligentDetector:
    """Enhanced detector with trained ML model and visualization."""
    
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
        self.rsrp_threshold_improvement = args.rsrp_improvement
        self.min_distance_to_anchor = args.min_dist_anchor
        self.enable_visualization = args.visualize
        self.viz_output_dir = Path(args.viz_dir)
        self.viz_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Load trained models
        model_path = Path(args.model_path)
        scaler_path = Path(args.scaler_path)
        self.ml_model = TrainedPingPongDetector(str(model_path), str(scaler_path))
        
        self.lambda_decay = 0.1
        self.r_anchor = args.r_anchor
        
        # State tracking
        self.ho_history = defaultdict(lambda: deque(maxlen=300))
        self.rsrp_history = defaultdict(lambda: defaultdict(deque))  # {ue_id: {gnb_id: [(time, rsrp), ...]}}
        self.seen_events = set()
        self.active_anchors = {}
        self.dc_assignments = {}
        self.assigned_ues = set()
        self.last_anchor_at = 0.0
        
        self.stats = {
            "evaluation_steps": 0,
            "anchors_deployed": 0,
            "dc_assignments": 0,
            "dc_smart_skipped": 0,
            "cost_benefit_rejections": 0,
            "errors": 0,
            "total_ho_events": 0,
            "hos_avoided": 0,
            "figures_saved": 0,
        }
    
    def run(self):
        """Main detection loop."""
        self._log(f"[OK] ML-ENHANCED Detector started (Trained Model)")
        self._log(f"═" * 70)
        self._log(f"  Model Status:")
        self._log(f"    • Model Loaded: {self.ml_model.model_loaded} ({type(self.ml_model.model).__name__ if self.ml_model.model else 'None'})")
        self._log(f"    • Scaler Loaded: {self.ml_model.scaler_loaded} ({type(self.ml_model.scaler).__name__ if self.ml_model.scaler else 'None'})")
        self._log(f"  Detection Parameters:")
        self._log(f"    • P_pp threshold: {self.ppp_threshold}")
        self._log(f"    • HO window: {self.window_s}s")
        self._log(f"    • RSRP improvement threshold: {self.rsrp_threshold_improvement:.1f} dB")
        self._log(f"    • Max distance to anchor: {self.min_distance_to_anchor:.0f} pixels")
        self._log(f"    • Visualization: {self.enable_visualization}")
        self._log(f"═" * 70)
        
        i = 0
        while self.max_iterations <= 0 or i < self.max_iterations:
            i += 1
            try:
                state = self._get_state()
                self._ingest_handovers(state)
                candidates = self._score_ues(state)
                clusters = self._cluster_candidates(candidates)
                self._evaluate_clusters(state, clusters, candidates)
                self._write_report(candidates, clusters)
                self._push_status()
                
            except KeyboardInterrupt:
                self._log("[OK] Detector stopped by user")
                break
            except Exception as exc:
                self.stats["errors"] += 1
                self._log(f"[ERROR] Error: {exc}")
            
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
        
        # Track RSRP history for visualization
        for uid, ue in state.get("ues", {}).items():
            serving = ue.get("serving")
            if serving:
                rsrp = float(ue.get("rsrp") or -120.0)
                sim_time = float(state.get("sim_time") or 0.0)
                self.rsrp_history[uid][serving].append((sim_time, rsrp))
                
                # Also track target if in HO
                if ue.get("target_gnb"):
                    self.rsrp_history[uid][ue.get("target_gnb")].append((sim_time, -120.0))
    
    def _score_ues(self, state) -> List[Dict]:
        """Score all UEs for ping-pong probability using trained model."""
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
            p_pp = self.ml_model.predict_proba(features["normalized"], ue_id=uid)
            
            if self.verbose:
                self._log(f"[SCORE] {uid}: HOs={len(events)}, "
                         f"HO_freq={features['ho_frequency']:.3f}, "
                         f"RSRP_var={features['rsrp_variance']:.3f}, "
                         f"Rev_ratio={features['reversal_ratio']:.3f}, "
                         f"Dir_flip={features['direction_flip']:.3f}, "
                         f"Osc={features['oscillation']:.3f} → "
                         f"P_pp={p_pp:.4f} (threshold={self.ppp_threshold})")
            
            if p_pp >= self.ppp_threshold:
                candidates.append({
                    "ue_id": uid,
                    "x": float(ue.get("x") or 0.0),
                    "y": float(ue.get("y") or 0.0),
                    "p_pp": p_pp,
                    "ho_count": len(events),
                    "sim_time": now,
                    "serving": ue.get("serving"),
                    "features": features,
                })
        
        return candidates
    
    def _extract_features(self, events: List[Dict], window_s: float) -> Dict:
        """Extract 5 ML features."""
        ho_frequency = len(events) / max(window_s, 1.0)
        f_ho_norm = min(1.0, ho_frequency / 0.5)
        
        rsrps = [float(ev.get("rsrp") or ev.get("RSRP_dBm") or -120.0) for ev in events]
        mean_rsrp = sum(rsrps) / len(rsrps) if rsrps else -120.0
        rsrp_variance = sum((v - mean_rsrp) ** 2 for v in rsrps) / len(rsrps) if rsrps else 1.0
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
    
    def _cluster_candidates(self, candidates: List[Dict]) -> List[List[Dict]]:
        """DBSCAN spatial clustering."""
        if len(candidates) < 3:
            if self.verbose and len(candidates) > 0:
                self._log(f"[DEBUG] Clustering: {len(candidates)} candidates (need 3+ for cluster)")
            return []
        
        remaining = list(candidates)
        clusters = []
        
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            changed = True
            
            while changed:
                changed = False
                to_remove = []
                
                for cand in remaining:
                    dist = self._dist(seed, cand)
                    if dist <= self.cluster_radius:
                        cluster.append(cand)
                        to_remove.append(cand)
                        changed = True
                
                for cand in to_remove:
                    remaining.remove(cand)
            
            if len(cluster) >= 3:
                if self.verbose:
                    self._log(f"[DEBUG] Cluster formed: {len(cluster)} UEs")
                clusters.append(cluster)
        
        return clusters
    
    def _evaluate_clusters(self, state: Dict, clusters: List[List[Dict]], candidates: List[Dict]):
        """Evaluate clusters and deploy anchors."""
        self.stats["evaluation_steps"] += 1
        now = float(state.get("sim_time") or 0.0)
        
        for cluster_idx, cluster in enumerate(clusters):
            cx, cy = self._weighted_centroid(cluster, now)
            cx, cy = self._optimize_anchor_position((cx, cy), cluster)
            
            r_max = max(self._dist(c, {"x": cx, "y": cy}) for c in cluster)
            if r_max > self.r_anchor:
                continue
            
            weights = [math.exp(-self.lambda_decay * (now - c.get("sim_time", now))) 
                      for c in cluster]
            score_k = sum(w * c["p_pp"] for w, c in zip(weights, cluster))
            
            if score_k < self.cluster_threshold:
                continue
            
            # Cost-benefit check
            ho_saved = sum(c["ho_count"] for c in cluster)
            benefit = ho_saved * self.c_ho
            cost = self.c_anchor
            
            if benefit <= cost:
                self.stats["cost_benefit_rejections"] += 1
                continue
            
            # Cooldown check
            if now - self.last_anchor_at < self.anchor_cooldown_s:
                continue
            
            self._deploy_anchor_and_smart_assign(cx, cy, cluster, benefit, score_k, state)
            self.last_anchor_at = now
            
            # Visualize anchor deployment
            if self.enable_visualization:
                self._visualize_cluster(cluster, (cx, cy), state)
    
    def _weighted_centroid(self, cluster: List[Dict], now: float) -> Tuple[float, float]:
        """Compute weighted centroid."""
        weights = [math.exp(-self.lambda_decay * (now - c.get("sim_time", now))) 
                  for c in cluster]
        total_weight = sum(weights)
        if total_weight == 0:
            return cluster[0]["x"], cluster[0]["y"]
        
        cx = sum(w * c["x"] for w, c in zip(weights, cluster)) / total_weight
        cy = sum(w * c["y"] for w, c in zip(weights, cluster)) / total_weight
        
        return cx, cy
    
    def _path_loss_estimate(self, anchor_pos: Dict, ue_pos: Dict) -> float:
        """Estimate RSRP using ITU path loss."""
        distance = self._dist(anchor_pos, ue_pos)
        if distance < 1:
            distance = 1
        
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
                pos = (cx + dx, cy + dy)
                min_rsrp = min(self._path_loss_estimate({"x": pos[0], "y": pos[1]}, c) 
                              for c in cluster)
                if min_rsrp > best_min_rsrp:
                    best_min_rsrp = min_rsrp
                    best_pos = pos
        
        return best_pos
    
    def _deploy_anchor_and_smart_assign(self, x: float, y: float, 
                                        cluster: List[Dict], 
                                        benefit: float, score: float,
                                        state: Dict):
        """Deploy anchor and smart DC assignment."""
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
            resp = requests.post(f"{self.url}/api/deploy_anchor", json=payload, timeout=5)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            self._log(f"[ERROR] Anchor deployment failed: {e}")
            self.stats["errors"] += 1
            return
        
        anchor_id = data.get("anchor_gnb_id") or data.get("gnb_id")
        if not anchor_id:
            self._log(f"[ERROR] No anchor_id in response: {data}")
            return
        
        assigned = []
        anchor_pos = {"x": x, "y": y}
        gnbs = state.get("gnbs", {})
        
        for cand in cluster:
            ue_id = cand["ue_id"]
            ue_pos = {"x": cand["x"], "y": cand["y"]}
            
            # Find nearest gNB RSRP
            nearest_rsrp = -120.0
            for gnb_id, gnb in gnbs.items():
                if gnb_id != anchor_id:
                    dist = self._dist(ue_pos, gnb)
                    path_loss = 68.3 + 20 * math.log10(max(dist, 1)) + 32.5
                    rsrp = 50 - path_loss
                    nearest_rsrp = max(nearest_rsrp, rsrp)
            
            anchor_rsrp = self._path_loss_estimate(anchor_pos, ue_pos)
            distance_to_anchor = self._dist(ue_pos, anchor_pos)
            
            # Smart assignment: only if anchor provides significant improvement and is close
            if (anchor_rsrp > nearest_rsrp + self.rsrp_threshold_improvement and
                distance_to_anchor <= self.min_distance_to_anchor):
                
                try:
                    assign_payload = {
                        "ue_id": ue_id,
                        "anchor_gnb_id": anchor_id,
                    }
                    resp = requests.post(f"{self.url}/api/assign_dc", 
                                       json=assign_payload, timeout=5)
                    resp.raise_for_status()
                    assigned.append(ue_id)
                    self.assigned_ues.add(ue_id)
                    self.stats["dc_assignments"] += 1
                except Exception as e:
                    self._log(f"[ERROR] DC assignment failed for {ue_id}: {e}")
            else:
                self.stats["dc_smart_skipped"] += 1
        
        if assigned:
            self.active_anchors[anchor_id] = {
                "x": x,
                "y": y,
                "deployed_at": float(state.get("sim_time") or 0.0),
                "triggered_ues": [c["ue_id"] for c in cluster],
                "assigned_ues": assigned,
            }
            self._log(f"[OK] Anchor {anchor_id} deployed @ ({x:.0f},{y:.0f}) "
                     f"Score={score:.2f} Benefit={benefit:.1f}")
            self.stats["anchors_deployed"] += 1
        else:
                self._log(f"[ERROR] Anchor {anchor_id} deployed but no UEs assigned")
    def _visualize_cluster(self, cluster: List[Dict], anchor_pos: Tuple[float, float], state: Dict):
        """Generate visualization for detected cluster."""
        if not _MATPLOTLIB_OK:
            return
        
        try:
            with _MATPLOTLIB_LOCK:
                # Create combined plot for cluster
                fig, axes = plt.subplots(len(cluster), 1, figsize=(12, 4 * len(cluster)))
                if len(cluster) == 1:
                    axes = [axes]
                
                fig.patch.set_facecolor("#0d1117")
                
                for idx, ue in enumerate(cluster):
                    ax = axes[idx]
                    ax.set_facecolor("#161b22")
                    
                    ue_id = ue["ue_id"]
                    serving_gnb = ue.get("serving")
                    
                    # Get RSRP history
                    if ue_id in self.rsrp_history and serving_gnb in self.rsrp_history[ue_id]:
                        history = self.rsrp_history[ue_id][serving_gnb]
                        if history:
                            times, rsrps = zip(*list(history))
                            ax.plot(times, rsrps, color="#58a6ff", linewidth=2, 
                                   label=f"Serving ({serving_gnb})", zorder=2)
                            
                            # Mark HO events
                            for ev in self.ho_history[ue_id]:
                                ho_time = float(ev.get("time") or 0.0)
                                # Find RSRP at HO time
                                closest_idx = min(range(len(times)), 
                                                 key=lambda i: abs(times[i] - ho_time))
                                ax.plot(ho_time, rsrps[closest_idx], "o", markersize=12,
                                       markerfacecolor="none", markeredgecolor="#f85149",
                                       markeredgewidth=2, zorder=4)
                            
                            # Mark assigned to anchor
                            if ue_id in self.assigned_ues:
                                ax.axvline(x=max(times), color="#3fb950", linestyle="--",
                                          linewidth=2, alpha=0.8, label="Assigned to Anchor", zorder=3)
                                ax.plot(max(times), max(rsrps), "s", markersize=14,
                                       markerfacecolor="#3fb950", markeredgecolor="#3fb950",
                                       markeredgewidth=2, zorder=4)
                    
                    # Add reference lines
                    for lvl, lbl, col in [(-80, "−80 dBm (good)", "#3fb950"),
                                         (-95, "−95 dBm (fair)", "#d29922"),
                                         (-110, "−110 dBm (poor)", "#f85149")]:
                        ax.axhline(y=lvl, color=col, linestyle=":", linewidth=0.8, alpha=0.5)
                    
                    ax.set_xlabel("Simulation Time (s)", color="#8b949e", fontsize=10)
                    ax.set_ylabel("RSRP (dBm)", color="#8b949e", fontsize=10)
                    ax.set_title(f"UE {ue_id} — P_pp={ue['p_pp']:.2f}",
                               color="#e6edf3", fontsize=11, fontweight="bold")
                    ax.tick_params(colors="#6e7681")
                    ax.spines[:].set_color("#30363d")
                    ax.grid(color="#30363d", linestyle="--", linewidth=0.5, alpha=0.6)
                    ax.legend(facecolor="#1c2128", edgecolor="#30363d",
                            labelcolor="#e6edf3", fontsize=9)
                
                plt.suptitle(f"Ping-Pong Cluster @ Anchor ({anchor_pos[0]:.0f}, {anchor_pos[1]:.0f})",
                           color="#e6edf3", fontsize=12, fontweight="bold", y=0.995)
                plt.tight_layout()
                
                # Save figure
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                fig_path = self.viz_output_dir / f"cluster_{timestamp}.png"
                plt.savefig(fig_path, dpi=100, facecolor="#0d1117")
                plt.close(fig)
                
                self.stats["figures_saved"] += 1
                self._log(f"[OK] Visualization saved: {fig_path.name}")
        
        except Exception as e:
            self._log(f"[ERROR] Visualization error: {e}")
    
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
            "assigned_ues": list(self.assigned_ues),
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
            "figures_saved": self.stats["figures_saved"],
        }
        try:
            requests.post(f"{self.url}/api/detector_status", json=payload, timeout=5)
        except requests.RequestException:
            pass
    
    def _log(self, msg: str):
        """Log with timestamp."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {msg}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="ML-Enhanced Ping-Pong Detector with Trained Models & Visualization")
    parser.add_argument("--url", default="http://localhost:8080", 
                       help="Simulator server URL")
    parser.add_argument("--interval", type=float, default=0.5, 
                       help="Polling interval in seconds")
    parser.add_argument("--window", type=float, default=25.0, 
                       help="HO sliding window in seconds [INCREASED to 25s for 45s pattern]")
    parser.add_argument("--ppp-threshold", type=float, default=0.5, 
                       help="P_pp >= threshold for anchor deployment [SET to 0.5]")
    parser.add_argument("--cluster-threshold", type=float, default=0.5, 
                       help="Cluster score threshold [LOWERED to 0.5]")
    parser.add_argument("--cluster-radius", type=float, default=270.0, 
                       help="DBSCAN epsilon (canvas pixels) [INCREASED to 270]")
    parser.add_argument("--r-anchor", type=float, default=150.0, 
                       help="Anchor coverage radius (canvas pixels) [INCREASED to 150]")
    parser.add_argument("--cooldown", type=float, default=3.0, 
                       help="Min seconds between anchor deployments [REDUCED to 3s]")
    parser.add_argument("--ho-cost", type=float, default=0.7, 
                       help="Cost per unnecessary HO")
    parser.add_argument("--anchor-cost", type=float, default=1.0, 
                       help="Cost per AnchorGNB deployment")
    
    # ML model parameters
    parser.add_argument("--model-path", default="dt_model.pkl", 
                       help="Path to trained logistic regression model")
    parser.add_argument("--scaler-path", default="scaler.pkl", 
                       help="Path to feature scaler")
    
    # Optimized parameters
    parser.add_argument("--rsrp-improvement", type=float, default=0.5, 
                       help="Min RSRP improvement (dB) to assign DC [LOWERED to 0.5dB]")
    parser.add_argument("--min-dist-anchor", type=float, default=200.0, 
                       help="Max distance to anchor for DC (pixels) [INCREASED to 200px]")
    
    # Visualization
    parser.add_argument("--visualize", action="store_true",
                       help="Enable RSRP visualization plots")
    parser.add_argument("--viz-dir", default="handover_charts",
                       help="Output directory for visualization plots")
    
    parser.add_argument("--report", default="ml_enhanced_report.json", 
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
    MLEnhancedIntelligentDetector(parse_args()).run()
