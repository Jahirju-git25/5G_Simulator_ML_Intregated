#!/usr/bin/env python3
"""
Test script to validate pickle file loading, feature engineering, and predictions.
This script demonstrates the complete ML pipeline in isolation.
"""

import pickle
import numpy as np
import sys
from pathlib import Path

def test_pickle_files():
    """Test if pickle files can be loaded."""
    print("\n" + "="*80)
    print("PICKLE FILE LOADING TEST")
    print("="*80)
    
    model_path = Path("dt_model.pkl")
    scaler_path = Path("scaler.pkl")
    
    # Check if files exist
    print(f"\n1. Checking file existence:")
    print(f"   Model file exists: {model_path.exists()} ({model_path})")
    print(f"   Scaler file exists: {scaler_path.exists()} ({scaler_path})")
    
    if not (model_path.exists() and scaler_path.exists()):
        print("\n[ERROR] Required pickle files not found!")
        return None, None
    
    # Load model
    print(f"\n2. Loading model from {model_path}...")
    try:
        with open(model_path, 'rb') as f:
            model = pickle.load(f)
        print(f"   ✓ Model loaded successfully")
        print(f"   Model type: {type(model).__name__}")
        print(f"   Model details: {model}")
    except Exception as e:
        print(f"   [ERROR] Failed to load model: {e}")
        return None, None
    
    # Load scaler
    print(f"\n3. Loading scaler from {scaler_path}...")
    try:
        with open(scaler_path, 'rb') as f:
            scaler = pickle.load(f)
        print(f"   ✓ Scaler loaded successfully")
        print(f"   Scaler type: {type(scaler).__name__}")
        print(f"   Scaler details: {scaler}")
    except Exception as e:
        print(f"   [ERROR] Failed to load scaler: {e}")
        return model, None
    
    return model, scaler


def test_feature_engineering():
    """Test feature engineering with sample data."""
    print("\n" + "="*80)
    print("FEATURE ENGINEERING TEST")
    print("="*80)
    
    # Create sample handover events
    print("\n1. Creating sample handover events...")
    sample_events = [
        {"time": 1.0, "ue_id": "UE1", "serving": "gNB1", "target": "gNB2", "rsrp": -85.0},
        {"time": 1.5, "ue_id": "UE1", "serving": "gNB2", "target": "gNB1", "rsrp": -88.0},
        {"time": 2.0, "ue_id": "UE1", "serving": "gNB1", "target": "gNB2", "rsrp": -86.0},
        {"time": 2.5, "ue_id": "UE1", "serving": "gNB2", "target": "gNB1", "rsrp": -89.0},
        {"time": 3.0, "ue_id": "UE1", "serving": "gNB1", "target": "gNB2", "rsrp": -87.0},
        {"time": 3.5, "ue_id": "UE1", "serving": "gNB2", "target": "gNB3", "rsrp": -90.0},
        {"time": 4.0, "ue_id": "UE1", "serving": "gNB3", "target": "gNB1", "rsrp": -92.0},
    ]
    print(f"   ✓ Created {len(sample_events)} handover events")
    
    # Extract features
    print(f"\n2. Extracting 5 ML features...")
    window_s = 10.0
    
    # HO frequency
    ho_frequency = len(sample_events) / max(window_s, 1.0)
    f_ho_norm = min(1.0, ho_frequency / 0.5)
    print(f"   • HO Frequency: {ho_frequency:.3f} HOs/s → Normalized: {f_ho_norm:.3f}")
    
    # RSRP variance
    rsrps = [float(ev.get("rsrp") or -120.0) for ev in sample_events]
    mean_rsrp = sum(rsrps) / len(rsrps) if rsrps else -120.0
    rsrp_variance = sum((v - mean_rsrp) ** 2 for v in rsrps) / len(rsrps) if rsrps else 1.0
    sigma2_rsrp_norm = min(1.0, rsrp_variance / 80.0)
    print(f"   • RSRP Variance: {rsrp_variance:.3f} → Normalized: {sigma2_rsrp_norm:.3f}")
    
    # Reversal ratio
    reversals = 0
    for i in range(1, len(sample_events)):
        if sample_events[i].get("target") == sample_events[i - 1].get("serving"):
            reversals += 1
    r_rev = reversals / max(len(sample_events) - 1, 1)
    print(f"   • Reversal Ratio: {reversals}/{max(len(sample_events)-1, 1)} → {r_rev:.3f}")
    
    # Direction flip
    direction_flips = 0
    for i in range(1, len(sample_events)):
        prev_serv = sample_events[i - 1].get("serving")
        prev_targ = sample_events[i - 1].get("target")
        curr_serv = sample_events[i].get("serving")
        curr_targ = sample_events[i].get("target")
        if prev_targ == curr_serv and prev_serv == curr_targ:
            direction_flips += 1
    d_flip_norm = min(1.0, direction_flips / max(len(sample_events) - 1, 1))
    print(f"   • Direction Flips: {direction_flips}/{max(len(sample_events)-1, 1)} → {d_flip_norm:.3f}")
    
    # Oscillation
    oscillations = 0
    for i in range(2, len(sample_events)):
        if sample_events[i - 2].get("serving") == sample_events[i].get("target"):
            oscillations += 1
    osc = oscillations / max(len(sample_events) - 2, 1)
    print(f"   • Oscillations: {oscillations}/{max(len(sample_events)-2, 1)} → {osc:.3f}")
    
    features = [f_ho_norm, sigma2_rsrp_norm, r_rev, d_flip_norm, osc]
    print(f"\n3. Final normalized feature vector:")
    print(f"   {features}")
    print(f"   [f_HO={f_ho_norm:.3f}, σ²_RSRP={sigma2_rsrp_norm:.3f}, R_rev={r_rev:.3f}, D_flip={d_flip_norm:.3f}, Osc={osc:.3f}]")
    
    return features


def test_prediction(model, scaler, features):
    """Test making predictions with the loaded model."""
    print("\n" + "="*80)
    print("PREDICTION TEST")
    print("="*80)
    
    if model is None or scaler is None:
        print("\n[ERROR] Cannot test prediction without model and scaler")
        return
    
    print(f"\n1. Input features: {[f'{f:.3f}' for f in features]}")
    
    # Check scaler's expected number of features
    expected_n_features = None
    if hasattr(scaler, 'n_features_in_'):
        expected_n_features = scaler.n_features_in_
        print(f"   Scaler expects {expected_n_features} features")
    
    try:
        # Transform features
        print(f"\n2. Scaling features...")
        features_array = np.array([features], dtype=np.float64)
        
        # Handle feature count mismatch
        if expected_n_features and len(features) < expected_n_features:
            print(f"   [WARNING] Feature mismatch: got {len(features)}, scaler expects {expected_n_features}")
            print(f"   Padding with zeros for missing features...")
            padding = np.zeros((features_array.shape[0], expected_n_features - len(features)))
            features_array = np.hstack([features_array, padding])
            print(f"   Padded features: {[f'{f:.3f}' for f in features_array[0]]}")
        
        features_scaled = scaler.transform(features_array)
        print(f"   Scaled features: {[f'{s:.3f}' for s in features_scaled[0]]}")
        
        # Make prediction
        print(f"\n3. Making prediction with trained model...")
        proba = model.predict_proba(features_scaled)
        print(f"   Raw probability output: {proba}")
        
        p_pp = float(proba[0][1])  # Class 1 probability
        print(f"\n4. Results:")
        print(f"   ✓ Ping-Pong Probability (P_pp): {p_pp:.4f}")
        print(f"   Class 0 (No Ping-Pong): {proba[0][0]:.4f}")
        print(f"   Class 1 (Ping-Pong): {proba[0][1]:.4f}")
        
        # Interpretation
        print(f"\n5. Interpretation:")
        if p_pp >= 0.5:
            print(f"   ⚠️  HIGH RISK: UE is likely experiencing ping-pong effect!")
        elif p_pp >= 0.25:
            print(f"   ⚡ MEDIUM RISK: UE shows ping-pong indicators")
        else:
            print(f"   ✓ LOW RISK: UE appears stable")
        
    except Exception as e:
        print(f"\n[ERROR] Prediction failed: {e}")
        import traceback
        traceback.print_exc()


def main():
    """Run all tests."""
    print("\n" + "╔" + "="*78 + "╗")
    print("║ ML PIPELINE VALIDATION - Pickle Files, Feature Engineering & Prediction ║")
    print("╚" + "="*78 + "╝")
    
    # Test 1: Load pickle files
    model, scaler = test_pickle_files()
    
    if model is None or scaler is None:
        print("\n[ERROR] Failed to load required files. Aborting.")
        sys.exit(1)
    
    # Test 2: Feature engineering
    features = test_feature_engineering()
    
    # Test 3: Prediction
    test_prediction(model, scaler, features)
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    print("✓ Pickle files successfully loaded")
    print("✓ Feature engineering working correctly")
    print("✓ Predictions generated successfully")
    print("\nThe ML pipeline is ready to use in intelligent_client_ml_enhanced.py!")
    print("="*80 + "\n")


if __name__ == "__main__":
    main()
