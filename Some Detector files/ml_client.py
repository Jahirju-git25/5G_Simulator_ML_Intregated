#!/usr/bin/env python3
"""
External intelligent ping-pong HO detector and AnchorGNB assigner.

Run from the server machine:
    python ml_client.py --url http://localhost:8080 --verbose

Run from another PC on the same network:
    python ml_client.py --url http://SERVER_IP:8080 --verbose
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
from urllib.parse import urlparse

import requests


class PingPongDetectorClient:
    def __init__(self, args):
        self.url = args.url.rstrip("/")
        self.interval = args.interval
        self.window_s = args.window
        self.theta_ue = args.theta_ue
        self.theta_cluster = args.theta_cluster
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

        self.ho_history = defaultdict(lambda: deque(maxlen=200))
        self.seen_events = set()
        self.active_anchors = {}
        self.last_anchor_at = 0.0
        self.stats = {
            "evaluation_steps": 0,
            "anchors_deployed": 0,
            "cost_benefit_rejections": 0,
            "false_positives": 0,
            "errors": 0,
            "total_ho_events": 0,
        }

    def run(self):
        self._log(f"Detector connected to {self.url}")
        self._log(f"Remote mode ready. Use --url http://SERVER_IP:8080 from another PC.")
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
        resp = requests.get(f"{self.url}/api/get_state", timeout=5)
        resp.raise_for_status()
        return resp.json()

    def _ingest_handovers(self, state):
        for ev in state.get("handover_events", []):
            key = (ev.get("step"), ev.get("ue_id"), ev.get("serving"), ev.get("target"))
            if key in self.seen_events:
                continue
            self.seen_events.add(key)
            uid = ev.get("ue_id")
            if uid:
                self.ho_history[uid].append(ev)
                self.stats["total_ho_events"] += 1

    def _score_ues(self, state):
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
            features = self._features(events, self.window_s)
            p_pp = self._predict_probability(features)
            if p_pp >= self.theta_ue:
                candidates.append({
                    "ue_id": uid,
                    "x": float(ue.get("x", 0.0)),
                    "y": float(ue.get("y", 0.0)),
                    "p_pp": p_pp,
                    "features": features,
                    "ho_count": len(events),
                    "last_pair": self._last_pair(events),
                })
                self._log(
                    f"{uid:6s} P_pp={p_pp:.2f} HOs={len(events)} "
                    f"rev={features['reversal_ratio']:.2f} osc={features['oscillation']:.2f}")
        return candidates

    def _features(self, events, window_s):
        ho_rate = len(events) / max(window_s, 1.0)
        rsrps = [float(ev.get("rsrp") or ev.get("RSRP_dBm") or -120.0) for ev in events]
        mean = sum(rsrps) / len(rsrps)
        var = sum((v - mean) ** 2 for v in rsrps) / len(rsrps)
        reversals = 0
        oscillations = 0
        for i in range(1, len(events)):
            if events[i].get("target") == events[i - 1].get("serving"):
                reversals += 1
        for i in range(2, len(events)):
            if events[i - 2].get("serving") == events[i].get("target"):
                oscillations += 1
        return {
            "ho_frequency": min(1.0, ho_rate / 0.45),
            "rsrp_variance": min(1.0, var / 80.0),
            "reversal_ratio": reversals / max(len(events) - 1, 1),
            "direction_flip": reversals / max(len(events) - 1, 1),
            "oscillation": oscillations / max(len(events) - 2, 1),
            "ho_rate_raw": ho_rate,
        }

    def _predict_probability(self, f):
        z = (
            -2.0
            + 1.6 * f["ho_frequency"]
            + 0.8 * f["rsrp_variance"]
            + 1.7 * f["reversal_ratio"]
            + 1.0 * f["direction_flip"]
            + 1.8 * f["oscillation"]
        )
        return 1.0 / (1.0 + math.exp(-z))

    def _last_pair(self, events):
        ev = events[-1]
        return ev.get("serving"), ev.get("target")

    def _cluster_candidates(self, candidates):
        remaining = list(candidates)
        clusters = []
        while remaining:
            seed = remaining.pop(0)
            cluster = [seed]
            changed = True
            while changed:
                changed = False
                for cand in list(remaining):
                    if any(self._dist(cand, other) <= self.cluster_radius for other in cluster):
                        cluster.append(cand)
                        remaining.remove(cand)
                        changed = True
            if len(cluster) >= 2:
                clusters.append(cluster)
        return clusters

    def _evaluate_clusters(self, state, clusters):
        self.stats["evaluation_steps"] += 1
        for cluster in clusters:
            cx = sum(c["x"] * c["p_pp"] for c in cluster) / sum(c["p_pp"] for c in cluster)
            cy = sum(c["y"] * c["p_pp"] for c in cluster) / sum(c["p_pp"] for c in cluster)
            if self._near_existing_anchor(cx, cy):
                continue
            avg_rate = sum(c["features"]["ho_rate_raw"] for c in cluster) / len(cluster)
            benefit = len(cluster) * self.c_ho * avg_rate * self.window_s - self.c_anchor
            score = len(cluster) * sum(c["p_pp"] for c in cluster) / len(cluster)
            if benefit <= 0 or score < self.theta_cluster:
                self.stats["cost_benefit_rejections"] += 1
                continue
            if time.time() - self.last_anchor_at < self.anchor_cooldown_s:
                continue
            self._deploy_anchor(cx, cy, cluster, benefit, score)

    def _deploy_anchor(self, x, y, cluster, benefit, score):
        payload = {
            "x": round(x, 1),
            "y": round(y, 1),
            "tx_power": 50,
            "num_sectors": 6,
            "is_anchor": True,
            "triggered_by": ",".join(c["ue_id"] for c in cluster),
            "ho_count": sum(c["ho_count"] for c in cluster),
        }
        resp = requests.post(f"{self.url}/api/add_anchor_gnb", json=payload, timeout=5)
        resp.raise_for_status()
        data = resp.json()
        anchor_id = data.get("anchor_gnb_id") or data.get("gnb_id")
        if not anchor_id:
            raise RuntimeError(f"Anchor deployment failed: {data}")

        assigned = []
        for cand in cluster:
            senb = cand["last_pair"][1] or cand["last_pair"][0]
            assign_payload = {
                "ue_id": cand["ue_id"],
                "anchor_gnb_id": anchor_id,
                "preferred_senb_id": senb,
            }
            requests.post(f"{self.url}/api/anchor/assign", json=assign_payload, timeout=5)
            if self.tcp_enabled:
                self._tcp_assign(cand["ue_id"], anchor_id)
            assigned.append(cand["ue_id"])

        self.active_anchors[anchor_id] = {
            "x": round(x, 1),
            "y": round(y, 1),
            "cluster_ues": assigned,
            "benefit": round(benefit, 3),
            "score": round(score, 3),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self.stats["anchors_deployed"] += 1
        self.last_anchor_at = time.time()
        self._log(
            f"ANCHOR DEPLOYED: {anchor_id} @ ({x:.0f},{y:.0f}) "
            f"UEs={assigned} benefit={benefit:.2f} score={score:.2f}")

    def _tcp_assign(self, ue_id, anchor_id):
        try:
            with socket.create_connection((self.tcp_host, self.tcp_port), timeout=3) as sock:
                sock.sendall(f"ASSIGN_ANCHOR:{ue_id}:{anchor_id}\n".encode("utf-8"))
                sock.recv(1024)
        except OSError as exc:
            self._log(f"TCP assign skipped for {ue_id}: {exc}")

    def _near_existing_anchor(self, x, y):
        for anchor in self.active_anchors.values():
            if math.hypot(x - anchor["x"], y - anchor["y"]) <= self.cluster_radius:
                return True
        return False

    def _write_report(self, candidates, clusters):
        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "stats": self.stats,
            "active_anchors": self.active_anchors,
            "candidate_ues": candidates,
            "clusters": [[c["ue_id"] for c in cluster] for cluster in clusters],
        }
        self.report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    def _push_status(self):
        payload = {
            "evaluation_steps": self.stats["evaluation_steps"],
            "active_anchors": list(self.active_anchors.keys()),
            "cost_benefit_rejections": self.stats["cost_benefit_rejections"],
            "false_positives": self.stats["false_positives"],
            "ue_count": len(self.ho_history),
            "errors": self.stats["errors"],
        }
        try:
            requests.post(f"{self.url}/api/update_detector_status", json=payload, timeout=2)
        except requests.RequestException:
            pass

    def _dist(self, a, b):
        return math.hypot(a["x"] - b["x"], a["y"] - b["y"])

    def _log(self, msg):
        if self.verbose:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def parse_args():
    parser = argparse.ArgumentParser(description="Intelligent ping-pong HO detector client")
    parser.add_argument("--url", default="http://localhost:8080", help="Simulator server URL")
    parser.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds")
    parser.add_argument("--window", type=float, default=12.0, help="Sliding HO window in seconds")
    parser.add_argument("--theta-ue", type=float, default=0.60, help="UE ping-pong probability threshold")
    parser.add_argument("--theta-cluster", type=float, default=1.40, help="Cluster deployment score threshold")
    parser.add_argument("--cluster-radius", type=float, default=150.0, help="Cluster radius in canvas pixels")
    parser.add_argument("--cooldown", type=float, default=8.0, help="Minimum seconds between anchor deployments")
    parser.add_argument("--ho-cost", type=float, default=0.70, help="Cost weight per avoidable HO")
    parser.add_argument("--anchor-cost", type=float, default=1.0, help="Cost of one AnchorGNB deployment")
    parser.add_argument("--report", default="ml_client_report.json", help="JSON report output path")
    parser.add_argument("--tcp", action="store_true", help="Also send ASSIGN_ANCHOR commands over TCP")
    parser.add_argument("--tcp-host", default=None, help="TCP host, defaults to host from --url")
    parser.add_argument("--tcp-port", type=int, default=5555, help="Anchor TCP port")
    parser.add_argument("--max-iterations", type=int, default=0, help="Stop after N polls; 0 runs forever")
    parser.add_argument("--verbose", action="store_true", help="Print live detector decisions")
    return parser.parse_args()


if __name__ == "__main__":
    PingPongDetectorClient(parse_args()).run()
