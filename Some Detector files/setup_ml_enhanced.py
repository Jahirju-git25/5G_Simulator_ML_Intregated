#!/usr/bin/env python3
"""
Quick Setup & Verification Script for ML-Enhanced Detector

Verifies:
  - Model files exist and are loadable
  - Dependencies are installed
  - Output directories are ready
  - Example visualization generation
"""

import sys
import json
import pickle
from pathlib import Path


def check_models():
    """Verify model files."""
    print("\n" + "="*60)
    print("CHECKING MODEL FILES")
    print("="*60)
    
    model_path = Path("pingpong_model.pkl")
    scaler_path = Path("scaler.pkl")
    
    if model_path.exists():
        try:
            with open(model_path, 'rb') as f:
                model = pickle.load(f)
            print(f"✓ Model found: {model_path}")
            print(f"  Type: {type(model).__name__}")
            print(f"  Size: {model_path.stat().st_size} bytes")
        except Exception as e:
            print(f"✗ Model corrupted: {e}")
            return False
    else:
        print(f"✗ Model not found: {model_path}")
        return False
    
    if scaler_path.exists():
        try:
            with open(scaler_path, 'rb') as f:
                scaler = pickle.load(f)
            print(f"✓ Scaler found: {scaler_path}")
            print(f"  Type: {type(scaler).__name__}")
            print(f"  Size: {scaler_path.stat().st_size} bytes")
        except Exception as e:
            print(f"✗ Scaler corrupted: {e}")
            return False
    else:
        print(f"✗ Scaler not found: {scaler_path}")
        return False
    
    return True


def check_dependencies():
    """Verify required Python packages."""
    print("\n" + "="*60)
    print("CHECKING DEPENDENCIES")
    print("="*60)
    
    required = {
        'requests': 'API communication',
        'numpy': 'Numerical computing',
        'sklearn': 'ML model loading',
        'matplotlib': 'Visualization',
    }
    
    missing = []
    
    for pkg, desc in required.items():
        try:
            __import__(pkg.replace('-', '_'))
            print(f"✓ {pkg:20s} ({desc})")
        except ImportError:
            print(f"✗ {pkg:20s} ({desc}) - MISSING")
            missing.append(pkg)
    
    if missing:
        print(f"\n⚠  Install missing packages:")
        print(f"  pip install {' '.join(missing)}")
        return False
    
    return True


def setup_directories():
    """Create output directories."""
    print("\n" + "="*60)
    print("SETTING UP DIRECTORIES")
    print("="*60)
    
    dirs = [
        Path("handover_charts"),
        Path("reports"),
    ]
    
    for d in dirs:
        if not d.exists():
            d.mkdir(parents=True)
            print(f"✓ Created: {d}/")
        else:
            print(f"✓ Exists: {d}/")
    
    return True


def verify_model_inference():
    """Test model prediction."""
    print("\n" + "="*60)
    print("TESTING MODEL INFERENCE")
    print("="*60)
    
    try:
        with open("pingpong_model.pkl", 'rb') as f:
            model = pickle.load(f)
        
        with open("scaler.pkl", 'rb') as f:
            scaler = pickle.load(f)
        
        # Test features: [f_HO, σ²_RSRP, R_rev, D_flip, Osc]
        test_features = [[0.5, 0.6, 0.3, 0.4, 0.2]]
        
        # Scale
        features_scaled = scaler.transform(test_features)
        
        # Predict
        proba = model.predict_proba(features_scaled)
        
        print(f"✓ Test prediction successful")
        print(f"  Input: {test_features[0]}")
        print(f"  Scaled: {features_scaled[0]}")
        print(f"  P_pp (class 0): {proba[0][0]:.4f}")
        print(f"  P_pp (class 1): {proba[0][1]:.4f}")
        
        return True
    
    except Exception as e:
        print(f"✗ Inference test failed: {e}")
        return False


def show_quick_start():
    """Display quick start commands."""
    print("\n" + "="*60)
    print("QUICK START COMMANDS")
    print("="*60)
    
    commands = [
        ("Enhanced detector with visualization:", 
         "python intelligent_client_ml_enhanced.py --url http://localhost:8080 --visualize --verbose"),
        
        ("Enhanced detector without visualization:", 
         "python intelligent_client_ml_enhanced.py --url http://localhost:8080 --verbose"),
        
        ("Generate plots from existing report:", 
         "python visualization.py --report ml_enhanced_report.json --verbose"),
        
        ("Optimized detector (original):", 
         "python intelligent_client_optimized.py --url http://localhost:8080 --verbose"),
    ]
    
    for desc, cmd in commands:
        print(f"\n{desc}")
        print(f"  $ {cmd}")


def show_environment_info():
    """Display environment information."""
    print("\n" + "="*60)
    print("ENVIRONMENT INFO")
    print("="*60)
    
    print(f"Python: {sys.version}")
    print(f"Platform: {sys.platform}")
    print(f"Executable: {sys.executable}")
    
    cwd = Path.cwd()
    print(f"Working Dir: {cwd}")
    
    # List relevant files
    print(f"\nRelevant files in {cwd.name}:")
    for pattern in ["*.pkl", "*enhanced*.py", "visualization.py", "README*.md"]:
        matches = list(cwd.glob(pattern))
        for f in matches:
            size_kb = f.stat().st_size / 1024
            print(f"  • {f.name:40s} ({size_kb:6.1f} KB)")


def generate_sample_report():
    """Generate sample JSON report."""
    print("\n" + "="*60)
    print("GENERATING SAMPLE REPORT")
    print("="*60)
    
    sample_report = {
        "timestamp": "2026-06-03T12:00:00Z",
        "stats": {
            "evaluation_steps": 0,
            "anchors_deployed": 0,
            "dc_assignments": 0,
            "dc_smart_skipped": 0,
            "cost_benefit_rejections": 0,
            "errors": 0,
            "total_ho_events": 0,
            "hos_avoided": 0,
            "figures_saved": 0,
        },
        "ppp_threshold": 0.65,
        "active_anchors": {},
        "dc_assignments": {},
        "candidate_ues": [],
        "clusters": [],
        "assigned_ues": [],
    }
    
    report_path = Path("reports/sample_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, 'w') as f:
        json.dump(sample_report, f, indent=2)
    
    print(f"✓ Sample report: {report_path}")
    
    return report_path


def main():
    """Run setup verification."""
    print("\n")
    print("╔" + "="*58 + "╗")
    print("║" + " "*15 + "ML-ENHANCED DETECTOR SETUP" + " "*17 + "║")
    print("╚" + "="*58 + "╝")
    
    checks = [
        ("Models", check_models),
        ("Dependencies", check_dependencies),
        ("Directories", setup_directories),
        ("Model Inference", verify_model_inference),
    ]
    
    results = {}
    for name, check_fn in checks:
        results[name] = check_fn()
    
    # Show info
    show_environment_info()
    
    # Generate sample
    generate_sample_report()
    
    # Show quick start
    show_quick_start()
    
    # Summary
    print("\n" + "="*60)
    print("SETUP SUMMARY")
    print("="*60)
    
    all_ok = all(results.values())
    
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{name:20s}: {status}")
    
    print("\n" + "="*60)
    if all_ok:
        print("✓ ALL CHECKS PASSED - Ready to run detector!")
        print("\nNext steps:")
        print("  1. Start simulator on http://localhost:8080")
        print("  2. Run: python intelligent_client_ml_enhanced.py --visualize --verbose")
        print("  3. Check handover_charts/ for generated plots")
        print("  4. Review ml_enhanced_report.json for statistics")
        return 0
    else:
        print("✗ SOME CHECKS FAILED - See above for details")
        return 1


if __name__ == "__main__":
    sys.exit(main())
