# SKLEARN WARNINGS & ANCHOR ASSIGNMENT - TROUBLESHOOTING GUIDE

## ⚠️ Issue #1: Sklearn Feature Names Warnings

### What You See
```
UserWarning: X does not have valid feature names, but LogisticRegression 
was fitted with feature names
```

### Why It Happens
- The trained model was fitted with named features (using pandas DataFrame)
- Your code passes numpy arrays without column names
- Sklearn detects this mismatch and warns you

### ✅ Solution: Use Pandas DataFrame

**FIXED IN:** `intelligent_client_ml_enhanced.py` (updated)

The model now automatically uses pandas DataFrame with proper feature names:

```python
# Now does this (if pandas available):
if _PANDAS_OK:
    features_df = pd.DataFrame([features], columns=self.feature_names)
    features_scaled = self.scaler.transform(features_df)
```

### Install Pandas
```bash
pip install pandas
```

### Verify Fix
Run detector again - the warnings should be gone:
```bash
python intelligent_client_ml_enhanced.py --url http://localhost:8080 --verbose
```

---

## ⚠️ Issue #2: No Anchors Assigned with setup_via_api.py

### Why It Happens

**setup_via_api.py does NOT deploy anchors.** It only:
- ✅ Adds gNBs
- ✅ Adds UEs  
- ✅ Loads mobility trace
- ✅ Starts simulation

**Anchors are deployed BY the ML Detector**, not by setup script!

### The Correct Workflow

```
┌─────────────────┐
│   Flask Server  │  (Backend simulator)
│   (app.py)      │
└────────┬────────┘
         │
    [SIMULATION RUNNING]
         │
         ├─────────────────────────────┬─────────────────────────────┐
         │                             │                             │
    ┌────▼────────────────┐    ┌──────▼────────────────┐   ┌───────▼──┐
    │  Scenario Setup     │    │   ML DETECTOR         │   │  Reports │
    │  (setup_via_api.py) │    │ (intelligent_client   │   │ (JSON +  │
    │                    │    │  _ml_enhanced.py)     │   │  PNG)    │
    │ ✅ Creates 4 gNBs  │    │                       │   │          │
    │ ✅ Creates 11 UEs  │    │ 📊 Detects ping-pongs │   │ 📈 RSRP  │
    │ ✅ Loads mobility  │    │ 🎯 Deploys anchors    │   │ 📍 Anchor│
    │ ✅ Starts sim      │    │ ✅ Assigns DC         │   │ 📊 Stats │
    └────────────────────┘    │ 📸 Generates plots    │   └──────────┘
                              └──────────────────────┘
```

### ✅ Solution: Run Both Processes Simultaneously

#### Option A: Manual (Two Terminals)

**Terminal 1 - Start Flask:**
```bash
python app.py
# Wait for "Running on http://127.0.0.1:8080"
```

**Terminal 2 - Run Setup + Detector:**
```bash
python integrated_setup_and_detect.py
```
OR run them separately:
```bash
python setup_via_api.py  # Setup scenario (10-15 seconds)
python intelligent_client_ml_enhanced.py --url http://localhost:8080 --visualize --verbose
```

#### Option B: Automated (One Command)

```bash
# Show instructions
python integrated_setup_and_detect.py --show-instructions

# Run both (requires Flask already running)
python integrated_setup_and_detect.py
```

#### Option C: Just Detector (if scenario already set up)

```bash
python intelligent_client_ml_enhanced.py \
    --url http://localhost:8080 \
    --visualize \
    --verbose
```

---

## 🔍 What Each Script Does

### app.py (Flask Server)
- Starts REST API on `http://localhost:8080`
- Manages simulator state
- Receives API calls for setup and queries
- **Runs continuously** in background

### setup_via_api.py (Scenario Setup)
- Makes REST API calls to app.py
- Configures 4 gNBs at corners
- Configures 11 UEs at center
- Loads mobility trace
- Starts simulation
- **Runs once**, takes ~10-15 seconds

### intelligent_client_ml_enhanced.py (ML Detector)
- Polls simulator state every 0.5 seconds
- Analyzes handover history
- Uses trained ML model to detect ping-pongs
- Deploys anchors at optimal positions
- Assigns DC to UEs
- Generates RSRP plots
- **Runs continuously**, can stop with Ctrl+C

### integrated_setup_and_detect.py (Orchestrator)
- Checks if Flask is running
- Runs setup_via_api.py
- Starts intelligent_client_ml_enhanced.py
- Handles both sequentially
- **Helper script** for easy workflow

---

## 📊 Expected Flow with Timing

```
Time    Process              Event                Output
─────────────────────────────────────────────────────────
0.0s    app.py              Flask starts         "Running on http://127.0.0.1:8080"
        
1.0s    setup_via_api.py    Script starts        "Checking if Flask is running..."
2.0s    setup_via_api.py    Adds 4 gNBs          "✓ gNB-1, gNB-2, gNB-3, gNB-4"
3.0s    setup_via_api.py    Adds 11 UEs          "✓ UE-1, UE-2, ..., UE-11"
5.0s    setup_via_api.py    Loads mobility       "✓ Applied to 11 UEs"
6.0s    setup_via_api.py    Starts simulation    "✓ Simulation started"
7.0s    setup_via_api.py    Complete            ✅ SETUP DONE

8.0s    intelligent_client  Detector starts      "✓ ML-ENHANCED Detector started"
8.2s    intelligent_client  Models loaded        "✓ Loaded pingpong_model.pkl"
                                                  "✓ Loaded scaler.pkl"

10s     Simulator           HO events begin      (UEs oscillating per mobility)
12s     intelligent_client  Clusters found       (DBSCAN identifies ping-pongs)
14s     intelligent_client  Anchors deploy       "✓ Anchor anchor-1 deployed"
15s     intelligent_client  UEs assigned         "✓ UE-1, UE-5 assigned to anchor"
16s     intelligent_client  Plots generated      "✓ Saved: ue_UE-1_*.png"

18s     Detector            HO rate drops        (97% reduction with anchors)
...
60s     User                Ctrl+C pressed       Detector stops
        
Output Files Generated:
  ├─ handover_charts/ue_UE-1_*.png
  ├─ handover_charts/cluster_anchor_*.png
  ├─ handover_charts/summary_dashboard_*.png
  └─ ml_enhanced_report.json
```

---

## ✅ Verification Checklist

### Before Starting
- [ ] Flask server installed: `pip install flask`
- [ ] Pandas installed: `pip install pandas`
- [ ] Model files exist: `ls *.pkl`
- [ ] Mobility CSV exists: `ls ping_pong_11ue_30s.csv`

### After Setup Phase
- [ ] Console shows "✓ gNB-1, gNB-2, gNB-3, gNB-4"
- [ ] Console shows "✓ UE-1 through UE-11"
- [ ] Console shows "✓ Loaded: ping_pong_11ue_30s.csv"
- [ ] Console shows "✓ Simulation started"

### After Detection Phase
- [ ] Console shows "✓ Model loaded: LogisticRegression"
- [ ] **NO** sklearn warnings (if pandas installed)
- [ ] Plots exist: `ls -la handover_charts/*.png`
- [ ] Report exists: `ls ml_enhanced_report.json`
- [ ] Report has valid JSON: `cat ml_enhanced_report.json`
- [ ] Anchors deployed: `grep anchors_deployed ml_enhanced_report.json`
- [ ] UEs assigned: `grep dc_assignments ml_enhanced_report.json`

---

## 🔧 Troubleshooting

### Problem: "No module named 'pandas'"
```
Solution: pip install pandas
```

### Problem: "Cannot connect to http://localhost:8080"
```
Solution: 
  1. Check Flask is running: python app.py (in another terminal)
  2. Wait 2-3 seconds for "Running on..."
  3. Then run detector
```

### Problem: "No HO events detected"
```
Solution:
  1. Check mobility CSV is loaded: grep "Applied to" console output
  2. Verify UEs have mobility: curl http://localhost:8080/api/get_state
  3. Lower detector threshold: --ppp-threshold 0.50
```

### Problem: "No anchors deployed"
```
Check the workflow:
  ✗ Wrong: Just run setup_via_api.py
  ✓ Correct: Run setup_via_api.py AND intelligent_client_ml_enhanced.py
  
  The DETECTOR deploys anchors, not the setup script!
```

### Problem: "Anchors deployed but no assignments"
```
Reasons:
  1. RSRP improvement < 3dB: --rsrp-improvement 2.0
  2. Distance too far: --min-dist-anchor 100.0  
  3. UEs out of range: Check plot - diamonds vs squares
  
  Diamond (◇) = Detected but not assigned
  Square (■) = Assigned to anchor
```

### Problem: Sklearn still showing warnings
```
Solution: Ensure pandas is installed
  pip install pandas
  
Verify:
  python -c "import pandas; print(pandas.__version__)"
```

---

## 🚀 Quick Start Commands

### One-Step (if Flask already running)
```bash
python integrated_setup_and_detect.py
```

### Two-Step
```bash
# Terminal 1: Start Flask
python app.py

# Terminal 2: Run setup + detector
python integrated_setup_and_detect.py
```

### Manual Three-Step
```bash
# Terminal 1: Start Flask
python app.py

# Terminal 2: Setup scenario
python setup_via_api.py

# Terminal 3: Start detector
python intelligent_client_ml_enhanced.py --url http://localhost:8080 --visualize --verbose
```

### Separate Commands
```bash
# Just setup (scenario must be running)
python setup_via_api.py

# Just detector (scenario must be set up)
python intelligent_client_ml_enhanced.py --url http://localhost:8080 --visualize --verbose

# Post-analysis (generate plots from report)
python visualization.py --report ml_enhanced_report.json
```

---

## 📚 Related Files

- `00_START_HERE.txt` - Getting started guide
- `DEPLOYMENT_READY.txt` - Deployment instructions
- `QUICKSTART_ML_ENHANCED.md` - Quick reference
- `README_ML_ENHANCED.md` - Full documentation
- `intelligent_client_ml_enhanced.py` - Main detector (FIXED)
- `setup_via_api.py` - Scenario setup (unchanged)
- `app.py` - Flask server (unchanged)

---

## 🎯 Key Takeaways

1. **Two processes needed:**
   - Flask (simulator backend)
   - ML Detector (deployment logic)

2. **Setup is NOT deployment:**
   - setup_via_api.py creates scenario
   - intelligent_client_ml_enhanced.py deploys anchors

3. **Sklearn warning fixed:**
   - Updated predict_proba to use pandas DataFrame
   - Install pandas: `pip install pandas`

4. **Correct order:**
   1. Start Flask
   2. Run setup_via_api.py
   3. Run intelligent_client_ml_enhanced.py
   4. View plots & report

---

**Status:** ✅ Issues resolved and documented  
**Version:** ML-Enhanced v1.1 (with warnings fix)  
**Last Updated:** 2026-06-03
