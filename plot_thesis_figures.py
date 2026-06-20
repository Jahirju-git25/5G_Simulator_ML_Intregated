#!/usr/bin/env python3
"""
Generate thesis plots for 4 GNB, 11 UE scenario:
  Plot 1: Scatter plot of P_pp (probability score) vs handover count
           with decision boundary at τ = 0.25 and anchor deployment events
  Plot 2: Cluster topology visualization with DBSCAN ε=270 pixel radius
           and RSRP-optimized weighted centroid positions
"""

import json
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.patches import Circle, Rectangle
from pathlib import Path
from typing import Dict, List, Tuple

# Configuration
WORKSPACE_ROOT = Path("d:\\dell pc\\Desktop\\5G_Simulator_Ml_Intregated")
REPORT_FILE = WORKSPACE_ROOT / "ml_enhanced_report.json"
HANDOVER_LOG = WORKSPACE_ROOT / "Data_Driven_from_5G_Simulator" / "Data_From_5g_Ml_Synchronized" / "log" / "handover_log (4).csv"
OUTPUT_DIR = WORKSPACE_ROOT / "thesis_plots"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Plot styling
THESIS_FONT = "Times New Roman"
THESIS_FONTSIZE = 12
plt.rcParams['font.family'] = THESIS_FONT
plt.rcParams['font.size'] = THESIS_FONTSIZE

# Colors
COLOR_ABOVE_THRESHOLD = '#E74C3C'  # Red - above τ=0.25
COLOR_BELOW_THRESHOLD = '#3498DB'  # Blue - below τ=0.25
COLOR_ANCHOR_1 = '#2ECC71'         # Green
COLOR_ANCHOR_2 = '#F39C12'         # Orange
COLOR_ANCHOR_3 = '#9B59B6'         # Purple
COLOR_CLUSTER = '#95A5A6'          # Gray for cluster members
COLOR_CENTROID = '#E74C3C'         # Red for centroid
COLOR_DBSCAN_CIRCLE = '#3498DB'    # Blue for DBSCAN radius


def load_handover_log() -> pd.DataFrame:
    """Load handover log and count HOs per UE."""
    try:
        df = pd.read_csv(HANDOVER_LOG)
        return df
    except Exception as e:
        print(f"[ERROR] Failed to load handover log: {e}")
        return pd.DataFrame()


def extract_ue_statistics(df: pd.DataFrame) -> Dict[str, Dict]:
    """Extract handover counts and statistics per UE."""
    ue_stats = {}
    
    for ue_id in sorted(df['UE_ID'].unique()):
        ue_data = df[df['UE_ID'] == ue_id]
        ho_count = len(ue_data)
        ping_pong_count = len(ue_data[ue_data['Remarks'].str.contains('Ping-Pong', na=False)])
        
        ue_stats[ue_id] = {
            'ho_count': ho_count,
            'ping_pong_count': ping_pong_count,
            'unique_targets': len(ue_data['Target_gNB'].unique()),
        }
    
    return ue_stats


def load_report_data() -> Dict:
    """Load report data with PPP scores and anchor positions."""
    try:
        with open(REPORT_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load report: {e}")
        return {}


def prepare_plot_data(df: pd.DataFrame, report: Dict) -> Tuple[List[Dict], List[Dict]]:
    """Prepare data for both plots."""
    ue_stats = extract_ue_statistics(df)
    
    # Get PPP scores from report candidates
    ppp_map = {c['ue_id']: c['p_pp'] for c in report.get('candidate_ues', [])}
    
    # All UEs (1-11) with their statistics
    all_ues = []
    for ue_id in [f"UE-{i}" for i in range(1, 12)]:
        stats = ue_stats.get(ue_id, {'ho_count': 0})
        p_pp = ppp_map.get(ue_id, 0.0)
        
        all_ues.append({
            'ue_id': ue_id,
            'ho_count': stats['ho_count'],
            'p_pp': p_pp,
            'above_threshold': p_pp >= 0.25,
        })
    
    # Get anchor deployment info
    anchors = []
    for anchor_name, anchor_data in report.get('active_anchors', {}).items():
        anchors.append({
            'name': anchor_name,
            'x': anchor_data['x'],
            'y': anchor_data['y'],
            'deployed_at': anchor_data['deployed_at'],
            'triggered_ues': anchor_data.get('triggered_ues', []),
            'assigned_ues': anchor_data.get('assigned_ues', []),
        })
    
    # Get cluster info
    clusters = report.get('clusters', [])
    
    return all_ues, anchors, clusters


def plot_1_ppp_vs_ho_scatter(ues: List[Dict], anchors: List[Dict]):
    """
    Plot 1: Scatter plot of P_pp vs handover count with:
    - Decision boundary at τ = 0.25
    - Three anchor deployment events annotated
    """
    fig, ax = plt.subplots(figsize=(12, 8))
    
    # Separate UEs by threshold
    above_threshold = [u for u in ues if u['above_threshold']]
    below_threshold = [u for u in ues if not u['above_threshold']]
    
    # Plot below threshold
    if below_threshold:
        x_below = [u['ho_count'] for u in below_threshold]
        y_below = [u['p_pp'] for u in below_threshold]
        ax.scatter(x_below, y_below, s=150, alpha=0.6, c=COLOR_BELOW_THRESHOLD,
                  label='Non-Candidate UEs ($P_{pp} < 0.25$)', 
                  marker='o', edgecolors='black', linewidth=1.5)
    
    # Plot above threshold
    if above_threshold:
        x_above = [u['ho_count'] for u in above_threshold]
        y_above = [u['p_pp'] for u in above_threshold]
        ax.scatter(x_above, y_above, s=200, alpha=0.7, c=COLOR_ABOVE_THRESHOLD,
                  label='Candidate UEs ($P_{pp} \\geq 0.25$)', 
                  marker='s', edgecolors='darkred', linewidth=2)
    
    # Add UE labels
    for ue in ues:
        ax.annotate(ue['ue_id'], 
                   xy=(ue['ho_count'], ue['p_pp']),
                   xytext=(5, 5), textcoords='offset points',
                   fontsize=10, fontweight='bold')
    
    # Decision boundary at τ = 0.25
    ax.axhline(y=0.25, color='red', linestyle='--', linewidth=2.5, 
              label='Decision Boundary ($\\tau = 0.25$)', zorder=1)
    
    # Anchor deployment events (vertical lines)
    anchor_colors = [COLOR_ANCHOR_1, COLOR_ANCHOR_2, COLOR_ANCHOR_3]
    for i, anchor in enumerate(anchors[:3]):
        color = anchor_colors[i % 3]
        ax.axvline(x=anchor['deployed_at'], color=color, linestyle=':', linewidth=2,
                  alpha=0.7)
        
        # Add legend entry for each anchor
        ax.text(anchor['deployed_at'], ax.get_ylim()[1] * 0.95, 
               f"{anchor['name']}\nt={anchor['deployed_at']:.1f}s",
               rotation=0, fontsize=10, ha='center',
               bbox=dict(boxstyle='round', facecolor=color, alpha=0.3))
    
    ax.set_xlabel('Handover Count', fontsize=THESIS_FONTSIZE, fontweight='bold')
    ax.set_ylabel('$P_{\\mathrm{pp}}$ (Ping-Pong Probability)', fontsize=THESIS_FONTSIZE, fontweight='bold')
    ax.set_title('Scatter Plot: $P_{\\mathrm{pp}}$ vs Handover Count (4 GNBs, 11 UEs)\n' + 
                'Decision Boundary and Anchor Deployment Events', 
                fontsize=14, fontweight='bold', pad=20)
    
    ax.legend(loc='upper left', fontsize=11, framealpha=0.95)
    ax.grid(True, alpha=0.3, linestyle='--')
    ax.set_xlim(-1, max([u['ho_count'] for u in ues]) + 3)
    ax.set_ylim(-0.05, min(1.0, max([u['p_pp'] for u in ues]) + 0.15))
    
    plt.tight_layout()
    output_path = OUTPUT_DIR / "plot_1_ppp_vs_ho_scatter.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"[OK] Plot 1 saved to {output_path}")
    plt.close()


def plot_2_cluster_topology(ues: List[Dict], anchors: List[Dict], 
                            clusters: List[List[str]], report: Dict):
    """
    Plot 2: Cluster topology visualization showing:
    - Spatial proximity of UE candidates within DBSCAN ε=270 pixel radius
    - RSRP-optimized weighted centroid position for each anchor
    - Cluster members and anchor positions
    """
    fig, ax = plt.subplots(figsize=(14, 10))
    
    # Get candidate UE positions from report
    candidate_positions = {}
    for c in report.get('candidate_ues', []):
        candidate_positions[c['ue_id']] = {
            'x': c['x'],
            'y': c['y'],
            'p_pp': c['p_pp'],
        }
    
    # Plot grid background
    ax.set_facecolor('#F5F5F5')
    
    # Plot DBSCAN radius circles around each anchor (ε = 270 pixels)
    DBSCAN_EPSILON = 270
    
    for i, anchor in enumerate(anchors):
        anchor_color = [COLOR_ANCHOR_1, COLOR_ANCHOR_2, COLOR_ANCHOR_3][i % 3]
        
        # DBSCAN radius circle
        circle = Circle((anchor['x'], anchor['y']), DBSCAN_EPSILON, 
                       color=COLOR_DBSCAN_CIRCLE, fill=False, linestyle='--',
                       linewidth=2, alpha=0.5, label='DBSCAN $\\varepsilon = 270$ px' if i == 0 else '')
        ax.add_patch(circle)
        
        # Anchor position (star marker)
        ax.plot(anchor['x'], anchor['y'], marker='*', markersize=25, 
               color=anchor_color, label=f"{anchor['name']} (Centroid)",
               markeredgecolor='black', markeredgewidth=1.5, zorder=10)
        
        # Anchor label
        ax.text(anchor['x'], anchor['y'] - 40, anchor['name'], 
               ha='center', fontsize=10, fontweight='bold',
               bbox=dict(boxstyle='round', facecolor=anchor_color, alpha=0.3))
        
        # Get cluster members for this anchor
        cluster_members = []
        for triggered_ue in anchor['triggered_ues']:
            if triggered_ue in candidate_positions:
                cluster_members.append(triggered_ue)
        
        # Plot cluster members
        if cluster_members:
            for member_ue in cluster_members:
                pos = candidate_positions[member_ue]
                
                # Plot UE position
                ax.plot(pos['x'], pos['y'], marker='o', markersize=12,
                       color=COLOR_CLUSTER, alpha=0.7,
                       markeredgecolor='black', markeredgewidth=1,
                       label='Cluster Member (UE)' if member_ue == cluster_members[0] else '')
                
                # UE label with PPP score
                ax.text(pos['x'], pos['y'] + 25, f"{member_ue}\n($P_{{\\mathrm{{pp}}}}={pos['p_pp']:.2f}$)",
                       ha='center', fontsize=9,
                       bbox=dict(boxstyle='round', facecolor='white', alpha=0.7))
                
                # Draw line from UE to centroid
                ax.plot([pos['x'], anchor['x']], [pos['y'], anchor['y']], 
                       color=anchor_color, linestyle=':', alpha=0.5, linewidth=1.5)
    
    # All candidate UEs (not yet shown)
    for ue_id, pos in candidate_positions.items():
        if not any(ue_id in anchor['triggered_ues'] for anchor in anchors):
            ax.plot(pos['x'], pos['y'], marker='x', markersize=10,
                   color='gray', alpha=0.5, markeredgewidth=2)
            ax.text(pos['x'], pos['y'] + 20, ue_id, ha='center', fontsize=8, alpha=0.5)
    
    # Formatting
    ax.set_xlabel('X Position (pixels)', fontsize=THESIS_FONTSIZE, fontweight='bold')
    ax.set_ylabel('Y Position (pixels)', fontsize=THESIS_FONTSIZE, fontweight='bold')
    ax.set_title('Cluster Topology Visualization (4 GNBs, 11 UEs)\n' +
                'DBSCAN $\\varepsilon = 270$ pixels, RSRP-Optimized Centroids',
                fontsize=14, fontweight='bold', pad=20)
    
    # Remove duplicate labels in legend
    handles, labels = ax.get_legend_handles_labels()
    by_label = dict(zip(labels, handles))
    ax.legend(by_label.values(), by_label.keys(), loc='upper right', 
             fontsize=11, framealpha=0.95)
    
    ax.grid(True, alpha=0.3, linestyle='-', linewidth=0.5)
    ax.set_aspect('equal', adjustable='box')
    
    # Set reasonable axis limits
    if candidate_positions:
        all_x = [p['x'] for p in candidate_positions.values()] + [a['x'] for a in anchors]
        all_y = [p['y'] for p in candidate_positions.values()] + [a['y'] for a in anchors]
        
        margin = 100
        ax.set_xlim(min(all_x) - margin, max(all_x) + margin)
        ax.set_ylim(min(all_y) - margin, max(all_y) + margin)
    
    plt.tight_layout()
    output_path = OUTPUT_DIR / "plot_2_cluster_topology.png"
    plt.savefig(output_path, dpi=300, bbox_inches='tight')
    print(f"[OK] Plot 2 saved to {output_path}")
    plt.close()


def main():
    """Generate both thesis plots."""
    print("[THESIS PLOTTING] Starting generation of thesis figures...")
    
    # Load data
    print("[INFO] Loading handover log...")
    df_ho = load_handover_log()
    
    print("[INFO] Loading report...")
    report = load_report_data()
    
    if df_ho.empty or not report:
        print("[ERROR] Failed to load required data")
        return
    
    print(f"[INFO] Handover log loaded: {len(df_ho)} events")
    print(f"[INFO] Report loaded: {len(report.get('candidate_ues', []))} candidates")
    
    # Prepare data
    ues, anchors, clusters = prepare_plot_data(df_ho, report)
    
    print(f"[INFO] Prepared data for {len(ues)} UEs and {len(anchors)} anchors")
    
    # Print statistics
    print("\n[STATISTICS]")
    print(f"  Total UEs: {len(ues)}")
    print(f"  Candidate UEs (P_pp >= 0.25): {len([u for u in ues if u['above_threshold']])}")
    print(f"  Anchor deployments: {len(anchors)}")
    print(f"  PPP threshold: 0.25")
    print(f"  DBSCAN epsilon: 270 pixels")
    
    # Generate plots
    print("\n[PLOTTING] Generating Plot 1 (P_pp vs Handover Count)...")
    plot_1_ppp_vs_ho_scatter(ues, anchors)
    
    print("[PLOTTING] Generating Plot 2 (Cluster Topology)...")
    plot_2_cluster_topology(ues, anchors, clusters, report)
    
    print(f"\n[SUCCESS] Both plots generated in {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
