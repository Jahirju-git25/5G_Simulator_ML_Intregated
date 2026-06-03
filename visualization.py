#!/usr/bin/env python3
"""
Visualization Module for Ping-Pong Detection and Anchor Assignment.

Generates RSRP vs Time plots with:
  - HO event markers (circles at transition points)
  - Ping-pong pattern indicators (dense HO regions)
  - Anchor assignment markers (squares at end of plot)
  - Quality thresholds (good/fair/poor RSRP bands)
"""

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Circle
    import numpy as np
    _MATPLOTLIB_OK = True
    _MATPLOTLIB_LOCK = threading.Lock()
except ImportError:
    _MATPLOTLIB_OK = False
    _MATPLOTLIB_LOCK = None


class RSRPVisualization:
    """Generate RSRP visualization plots."""
    
    # Color scheme (GitHub dark theme)
    COLOR_GOOD = "#3fb950"
    COLOR_FAIR = "#d29922"
    COLOR_POOR = "#f85149"
    COLOR_SERVING = "#58a6ff"
    COLOR_TARGET = "#f0883e"
    COLOR_BG = "#0d1117"
    COLOR_PANEL = "#161b22"
    COLOR_TEXT = "#e6edf3"
    COLOR_GRID = "#30363d"
    COLOR_ANCHOR = "#3fb950"
    COLOR_HO = "#f85149"
    
    RSRP_THRESHOLDS = [
        (-80, "−80 dBm (good)", COLOR_GOOD),
        (-95, "−95 dBm (fair)", COLOR_FAIR),
        (-110, "−110 dBm (poor)", COLOR_POOR),
    ]
    
    def __init__(self, output_dir: str = "handover_charts", verbose: bool = False):
        """Initialize visualization."""
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
    
    def plot_ue_rsrp(self, ue_id: str, rsrp_history: Dict[str, List[Tuple[float, float]]],
                     ho_events: List[Dict], anchor_assigned: bool = False,
                     p_pp: float = 0.0) -> Path:
        """
        Plot RSRP vs Time for a single UE with HO markers.
        
        Args:
            ue_id: UE identifier
            rsrp_history: {gnb_id: [(time, rsrp), ...]}
            ho_events: [{"time": t, "serving": gnb1, "target": gnb2}, ...]
            anchor_assigned: Whether UE was assigned to anchor
            p_pp: Ping-pong probability score
        
        Returns:
            Path to saved figure
        """
        if not _MATPLOTLIB_OK:
            return None
        
        try:
            with _MATPLOTLIB_LOCK:
                fig, ax = plt.subplots(figsize=(14, 6))
                fig.patch.set_facecolor(self.COLOR_BG)
                ax.set_facecolor(self.COLOR_PANEL)
                
                # Find serving gNB (most recent HO)
                serving_gnb = None
                if ho_events:
                    serving_gnb = ho_events[-1].get("target")
                
                # Plot RSRP for serving gNB
                if serving_gnb and serving_gnb in rsrp_history:
                    times, rsrps = zip(*rsrp_history[serving_gnb])
                    ax.plot(times, rsrps, color=self.COLOR_SERVING, linewidth=2.5,
                           label=f"Serving ({serving_gnb})", zorder=2)
                    
                    # Add HO event markers
                    for idx, ho in enumerate(ho_events):
                        ho_time = float(ho.get("time", 0.0))
                        # Find closest RSRP to HO time
                        closest_idx = min(range(len(times)),
                                        key=lambda i: abs(times[i] - ho_time))
                        rsrp_at_ho = rsrps[closest_idx]
                        
                        # Draw circle marker
                        ax.plot(ho_time, rsrp_at_ho, "o", markersize=12,
                               markerfacecolor="none", markeredgecolor=self.COLOR_HO,
                               markeredgewidth=2.2, zorder=4, alpha=0.8)
                    
                    # Mark end of plot (final state)
                    if times:
                        final_time = times[-1]
                        final_rsrp = rsrps[-1]
                        
                        # Mark with square if assigned to anchor
                        if anchor_assigned:
                            ax.plot(final_time, final_rsrp, "s", markersize=14,
                                   markerfacecolor=self.COLOR_ANCHOR,
                                   markeredgecolor=self.COLOR_ANCHOR,
                                   markeredgewidth=2, zorder=5, label="Assigned to Anchor")
                            ax.axvline(x=final_time, color=self.COLOR_ANCHOR,
                                      linestyle="--", linewidth=1.5, alpha=0.6, zorder=3)
                        else:
                            # Mark as detection point
                            ax.plot(final_time, final_rsrp, "D", markersize=10,
                                   markerfacecolor="none", markeredgecolor=self.COLOR_TARGET,
                                   markeredgewidth=2, zorder=5, label="Detected Ping-Pong")
                
                # Plot target gNB if available
                if ho_events and len(ho_events) > 0:
                    target_gnb = ho_events[-1].get("serving")
                    if target_gnb and target_gnb in rsrp_history:
                        times, rsrps = zip(*rsrp_history[target_gnb])
                        ax.plot(times, rsrps, color=self.COLOR_TARGET, linewidth=2.5,
                               linestyle="--", label=f"Target ({target_gnb})", zorder=2)
                
                # Add quality threshold lines
                for threshold, label, color in self.RSRP_THRESHOLDS:
                    ax.axhline(y=threshold, color=color, linestyle=":",
                              linewidth=0.9, alpha=0.5, zorder=1)
                    ax.text(0.01, threshold + 1, label, color=color, fontsize=8,
                           alpha=0.7, transform=ax.get_yaxis_transform())
                
                # Formatting
                ax.set_xlabel("Simulation Time (s)", color="#8b949e", fontsize=11, fontweight="bold")
                ax.set_ylabel("RSRP (dBm)", color="#8b949e", fontsize=11, fontweight="bold")
                
                title = f"RSRP vs Time — {ue_id}"
                if ho_events:
                    ho_time = ho_events[-1].get("time", 0.0)
                    title += f" | HO @ t={float(ho_time):.2f}s"
                title += f" | P_pp={p_pp:.3f}"
                
                ax.set_title(title, color=self.COLOR_TEXT, fontsize=12, fontweight="bold")
                ax.tick_params(colors="#6e7681", labelsize=10)
                
                for spine in ax.spines.values():
                    spine.set_color(self.COLOR_GRID)
                    spine.set_linewidth(1)
                
                ax.grid(True, color=self.COLOR_GRID, linestyle="--", linewidth=0.6, alpha=0.4)
                ax.legend(loc="upper right", facecolor=self.COLOR_PANEL,
                         edgecolor=self.COLOR_GRID, labelcolor=self.COLOR_TEXT,
                         fontsize=10, framealpha=0.95)
                
                plt.tight_layout()
                
                # Save figure
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:21]
                fig_name = f"ue_{ue_id}_{timestamp}.png"
                fig_path = self.output_dir / fig_name
                plt.savefig(fig_path, dpi=120, facecolor=self.COLOR_BG, edgecolor="none")
                plt.close(fig)
                
                self._log(f"✓ Saved: {fig_name}")
                return fig_path
        
        except Exception as e:
            self._log(f"✗ Plot error: {e}")
            return None
    
    def plot_cluster_comparison(self, cluster_ues: List[str],
                               rsrp_histories: Dict[str, Dict[str, List[Tuple[float, float]]]],
                               ho_events_dict: Dict[str, List[Dict]],
                               anchor_pos: Tuple[float, float],
                               assigned_ues: List[str],
                               p_pp_scores: Dict[str, float]) -> Path:
        """
        Plot multiple UEs in cluster with anchor deployment.
        
        Args:
            cluster_ues: List of UE IDs in cluster
            rsrp_histories: {ue_id: {gnb_id: [(time, rsrp), ...]}}
            ho_events_dict: {ue_id: [ho_events]}
            anchor_pos: (x, y) anchor position
            assigned_ues: List of UE IDs assigned to anchor
            p_pp_scores: {ue_id: p_pp_score}
        
        Returns:
            Path to saved figure
        """
        if not _MATPLOTLIB_OK or len(cluster_ues) == 0:
            return None
        
        try:
            with _MATPLOTLIB_LOCK:
                n_ues = len(cluster_ues)
                fig, axes = plt.subplots(n_ues, 1, figsize=(14, 5 * n_ues))
                if n_ues == 1:
                    axes = [axes]
                
                fig.patch.set_facecolor(self.COLOR_BG)
                
                for plot_idx, ue_id in enumerate(cluster_ues):
                    ax = axes[plot_idx]
                    ax.set_facecolor(self.COLOR_PANEL)
                    
                    is_assigned = ue_id in assigned_ues
                    p_pp = p_pp_scores.get(ue_id, 0.0)
                    
                    # Plot RSRP history
                    if ue_id in rsrp_histories:
                        rsrp_hist = rsrp_histories[ue_id]
                        
                        # Get serving gNB
                        ho_list = ho_events_dict.get(ue_id, [])
                        serving_gnb = ho_list[-1].get("target") if ho_list else None
                        
                        if serving_gnb and serving_gnb in rsrp_hist:
                            times, rsrps = zip(*rsrp_hist[serving_gnb])
                            ax.plot(times, rsrps, color=self.COLOR_SERVING,
                                   linewidth=2.5, label=f"Serving ({serving_gnb})", zorder=2)
                            
                            # Mark HO events as circles
                            for ho in ho_list:
                                ho_time = float(ho.get("time", 0.0))
                                closest_idx = min(range(len(times)),
                                               key=lambda i: abs(times[i] - ho_time))
                                rsrp_at_ho = rsrps[closest_idx]
                                ax.plot(ho_time, rsrp_at_ho, "o", markersize=11,
                                       markerfacecolor="none", markeredgecolor=self.COLOR_HO,
                                       markeredgewidth=2, zorder=4, alpha=0.75)
                            
                            # Mark final state
                            if times:
                                final_time = times[-1]
                                final_rsrp = rsrps[-1]
                                
                                if is_assigned:
                                    # Green square = assigned
                                    ax.plot(final_time, final_rsrp, "s", markersize=13,
                                           color=self.COLOR_ANCHOR, markeredgewidth=2,
                                           zorder=5, label="✓ Assigned to Anchor")
                                    ax.axvline(x=final_time, color=self.COLOR_ANCHOR,
                                             linestyle="--", linewidth=1.8, alpha=0.6, zorder=3)
                                else:
                                    # Orange diamond = detected but not assigned
                                    ax.plot(final_time, final_rsrp, "D", markersize=10,
                                           markerfacecolor="none",
                                           markeredgecolor=self.COLOR_TARGET,
                                           markeredgewidth=2, zorder=5,
                                           label="✗ Detected, not assigned")
                    
                    # Add thresholds
                    for threshold, label, color in self.RSRP_THRESHOLDS:
                        ax.axhline(y=threshold, color=color, linestyle=":",
                                  linewidth=0.8, alpha=0.4, zorder=1)
                    
                    # Formatting
                    ax.set_xlabel("Simulation Time (s)", color="#8b949e", fontsize=10)
                    ax.set_ylabel("RSRP (dBm)", color="#8b949e", fontsize=10)
                    
                    status = "✓ Assigned" if is_assigned else "✗ Not Assigned"
                    ax.set_title(f"UE {ue_id} | P_pp={p_pp:.3f} | {status}",
                               color=self.COLOR_TEXT, fontsize=11, fontweight="bold")
                    ax.tick_params(colors="#6e7681", labelsize=9)
                    
                    for spine in ax.spines.values():
                        spine.set_color(self.COLOR_GRID)
                    
                    ax.grid(True, color=self.COLOR_GRID, linestyle="--",
                           linewidth=0.5, alpha=0.4)
                    ax.legend(loc="upper right", facecolor=self.COLOR_PANEL,
                             edgecolor=self.COLOR_GRID, labelcolor=self.COLOR_TEXT,
                             fontsize=9, framealpha=0.95)
                
                fig.suptitle(
                    f"Ping-Pong Cluster | Anchor @ ({anchor_pos[0]:.0f}, {anchor_pos[1]:.0f}) | "
                    f"{len(assigned_ues)}/{len(cluster_ues)} UEs Assigned",
                    color=self.COLOR_TEXT, fontsize=13, fontweight="bold", y=0.995
                )
                
                plt.tight_layout(rect=[0, 0, 1, 0.99])
                
                # Save figure
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")[:21]
                fig_name = f"cluster_anchor_{anchor_pos[0]:.0f}_{anchor_pos[1]:.0f}_{timestamp}.png"
                fig_path = self.output_dir / fig_name
                plt.savefig(fig_path, dpi=120, facecolor=self.COLOR_BG, edgecolor="none")
                plt.close(fig)
                
                self._log(f"✓ Saved cluster plot: {fig_name}")
                return fig_path
        
        except Exception as e:
            self._log(f"✗ Cluster plot error: {e}")
            return None
    
    def plot_summary_dashboard(self, report_path: str) -> Path:
        """Generate summary dashboard from report JSON."""
        if not _MATPLOTLIB_OK:
            return None
        
        try:
            with open(report_path, 'r') as f:
                report = json.load(f)
            
            stats = report.get("stats", {})
            
            with _MATPLOTLIB_LOCK:
                fig, axes = plt.subplots(2, 2, figsize=(14, 10))
                fig.patch.set_facecolor(self.COLOR_BG)
                
                # Plot 1: Stats bar chart
                ax = axes[0, 0]
                ax.set_facecolor(self.COLOR_PANEL)
                
                metrics = [
                    ("Anchors", stats.get("anchors_deployed", 0)),
                    ("Assigned", stats.get("dc_assignments", 0)),
                    ("Skipped", stats.get("dc_smart_skipped", 0)),
                    ("HOs Avoided", stats.get("hos_avoided", 0)),
                ]
                
                names, values = zip(*metrics)
                colors = [self.COLOR_GOOD, self.COLOR_ANCHOR, self.COLOR_FAIR, self.COLOR_GOOD]
                bars = ax.bar(names, values, color=colors, edgecolor=self.COLOR_GRID, linewidth=2)
                
                ax.set_ylabel("Count", color="#8b949e", fontsize=11)
                ax.set_title("Deployment Summary", color=self.COLOR_TEXT,
                           fontsize=12, fontweight="bold")
                ax.tick_params(colors="#6e7681")
                ax.set_facecolor(self.COLOR_PANEL)
                
                for spine in ax.spines.values():
                    spine.set_color(self.COLOR_GRID)
                
                # Add value labels
                for bar in bars:
                    height = bar.get_height()
                    ax.text(bar.get_x() + bar.get_width()/2., height,
                           f'{int(height)}', ha='center', va='bottom',
                           color=self.COLOR_TEXT, fontweight='bold')
                
                # Plot 2: Error rate
                ax = axes[0, 1]
                ax.set_facecolor(self.COLOR_PANEL)
                
                total_steps = stats.get("evaluation_steps", 1)
                errors = stats.get("errors", 0)
                error_rate = (errors / total_steps * 100) if total_steps > 0 else 0
                
                ax.barh(["Error Rate"], [error_rate], color=self.COLOR_POOR if error_rate > 5 else self.COLOR_FAIR,
                       edgecolor=self.COLOR_GRID, linewidth=2)
                ax.set_xlabel("Percentage (%)", color="#8b949e", fontsize=11)
                ax.set_title("System Error Rate", color=self.COLOR_TEXT,
                           fontsize=12, fontweight="bold")
                ax.tick_params(colors="#6e7681")
                ax.set_xlim(0, 20)
                
                for spine in ax.spines.values():
                    spine.set_color(self.COLOR_GRID)
                
                ax.text(error_rate + 0.5, 0, f"{error_rate:.1f}%",
                       color=self.COLOR_TEXT, fontweight='bold', va='center')
                
                # Plot 3: Cost-benefit summary
                ax = axes[1, 0]
                ax.set_facecolor(self.COLOR_PANEL)
                
                rejections = stats.get("cost_benefit_rejections", 0)
                deployments = stats.get("anchors_deployed", 0)
                
                data = [deployments, rejections]
                labels = ["Deployed", "Rejected\n(low benefit)"]
                colors_pie = [self.COLOR_GOOD, self.COLOR_FAIR]
                
                wedges, texts, autotexts = ax.pie(data, labels=labels, autopct='%1.1f%%',
                                                   colors=colors_pie, startangle=90,
                                                   textprops={'color': self.COLOR_TEXT,
                                                             'fontsize': 10})
                
                for autotext in autotexts:
                    autotext.set_color(self.COLOR_BG)
                    autotext.set_fontweight('bold')
                
                ax.set_title("Anchor Deployment Decisions", color=self.COLOR_TEXT,
                           fontsize=12, fontweight="bold")
                
                # Plot 4: Text summary
                ax = axes[1, 1]
                ax.axis("off")
                
                summary_text = f"""
DETECTOR STATISTICS SUMMARY
{'='*40}

Total Evaluation Steps:  {stats.get('evaluation_steps', 0)}
Total HO Events:         {stats.get('total_ho_events', 0)}
HOs Avoided:             {stats.get('hos_avoided', 0)}

Anchors Deployed:        {stats.get('anchors_deployed', 0)}
DC Assignments:          {stats.get('dc_assignments', 0)}
Smart Skip (dist):       {stats.get('dc_smart_skipped', 0)}
Cost-Benefit Rejections: {stats.get('cost_benefit_rejections', 0)}

System Errors:           {stats.get('errors', 0)}
Figures Generated:       {stats.get('figures_saved', 0)}

P_pp Threshold:          {report.get('ppp_threshold', 0.65):.2f}
Timestamp:               {report.get('timestamp', 'N/A')}
                """
                
                ax.text(0.1, 0.9, summary_text, transform=ax.transAxes,
                       fontsize=10, verticalalignment='top', fontfamily='monospace',
                       color=self.COLOR_TEXT, bbox=dict(boxstyle='round',
                       facecolor=self.COLOR_PANEL, edgecolor=self.COLOR_GRID, linewidth=2))
                
                plt.tight_layout()
                
                # Save
                timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
                fig_name = f"summary_dashboard_{timestamp}.png"
                fig_path = self.output_dir / fig_name
                plt.savefig(fig_path, dpi=120, facecolor=self.COLOR_BG, edgecolor="none")
                plt.close(fig)
                
                self._log(f"✓ Saved summary: {fig_name}")
                return fig_path
        
        except Exception as e:
            self._log(f"✗ Summary plot error: {e}")
            return None
    
    def _log(self, msg: str):
        """Log message."""
        if self.verbose:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] [Viz] {msg}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate visualization plots")
    parser.add_argument("--report", default="ml_enhanced_report.json",
                       help="JSON report path")
    parser.add_argument("--output-dir", default="handover_charts",
                       help="Output directory for plots")
    parser.add_argument("--verbose", action="store_true",
                       help="Print debug messages")
    
    args = parser.parse_args()
    
    viz = RSRPVisualization(output_dir=args.output_dir, verbose=args.verbose)
    
    if Path(args.report).exists():
        viz.plot_summary_dashboard(args.report)
        print(f"✓ Plots saved to {args.output_dir}/")
    else:
        print(f"✗ Report not found: {args.report}")
