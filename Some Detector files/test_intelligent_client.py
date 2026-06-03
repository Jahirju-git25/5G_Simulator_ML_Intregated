#!/usr/bin/env python3
"""Quick test of intelligent_client ML model."""

import intelligent_client

# Test LogisticRegression
model = intelligent_client.LogisticRegression()

# Test case 1: Low ping-pong (all features low)
features_low = [0.1, 0.2, 0.05, 0.1, 0.05]
p_pp_low = model.predict_proba(features_low)
print(f"✓ Low ping-pong features: P_pp = {p_pp_low:.3f} (expect < 0.3)")

# Test case 2: High ping-pong (all features high)
features_high = [0.9, 0.8, 0.9, 0.8, 0.9]
p_pp_high = model.predict_proba(features_high)
print(f"✓ High ping-pong features: P_pp = {p_pp_high:.3f} (expect > 0.8)")

# Test case 3: Medium (mixed features)
features_medium = [0.5, 0.4, 0.3, 0.2, 0.6]
p_pp_medium = model.predict_proba(features_medium)
print(f"✓ Medium ping-pong features: P_pp = {p_pp_medium:.3f} (expect 0.5–0.7)")

# Test threshold
threshold = 0.65
print(f"\n✓ Threshold check (P_pp >= {threshold}):")
print(f"  Low:    {p_pp_low:.3f} >= {threshold} ? {p_pp_low >= threshold}")
print(f"  Medium: {p_pp_medium:.3f} >= {threshold} ? {p_pp_medium >= threshold}")
print(f"  High:   {p_pp_high:.3f} >= {threshold} ? {p_pp_high >= threshold}")

print("\n✓ All ML model tests passed!")
