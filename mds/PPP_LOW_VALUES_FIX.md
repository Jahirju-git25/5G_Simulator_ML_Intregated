# 🔧 P_PP Low Values - Diagnosis & Fixes

## Problem Summary
- **CSV shows**: Clear ping-pong patterns (UE-1 to UE-6 oscillating 150→317→484→650→483→316→150)
- **ML client shows**: P_pp = 0.187-0.270 (all below 0.65 threshold)
- **Expected**: P_pp ≥ 0.8 for obvious ping-pong patterns

---

## Root Cause Analysis

### Possible Cause #1: Insufficient HO Events ⚠️
**Symptom:** Client shows "HOs=3, P_pp=0.187" for all UEs

**Why it happens:**
- Client requires ≥3 HO events in sliding window (line 233)
- Simulator's TTT (Time-To-Trigger) prevents fast HOs
- Position changes every 1 second, but TTT needs ~3 steps
- Result: Only ~1-2 HOs per evaluation cycle

**Check this:**
```bash
# Run diagnostic
python check_ppp_diagnostic.py

# Look for: "HOs per UE: UE-1: XX HOs"
# If XX ≤ 3, this is the issue
```

**Fixes:**
1. **Lower TTT** (easiest):
   ```bash
   curl -X POST http://localhost:8080/api/set_params \
     -H "Content-Type: application/json" \
     -d '{"ttt_steps": 1}'
   ```
   - Default: 3 steps (too high for 1-second movements)
   - Try: 1 step (immediate HO)

2. **Increase window size**:
   ```bash
   python intelligent_client_ml_enhanced.py \
     --url http://localhost:8080 \
     --window 20  # Default is 12
   ```
   - Allows more HO events to accumulate

3. **Lower hysteresis**:
   ```bash
   curl -X POST http://localhost:8080/api/set_params \
     -H "Content-Type: application/json" \
     -d '{"hysteresis": 1}' # Default might be 2-3 dB
   ```
   - Makes HOs trigger more easily

---

### Possible Cause #2: Feature Values Don't Match Training ⚠️⚠️
**Symptom:** HOs detected but features show low reversal/oscillation

**Why it happens:**
- Model trained on **real network patterns**
- Synthetic oscillation pattern may not match training distribution
- Features like `R_rev` and `D_flip` might be lower than expected

**Check this:**
```bash
python check_ppp_diagnostic.py

# Look for feature values:
# f_HO:           0.1234 
# R_rev:          0.5000  ← Should be HIGH (>0.8)
# D_flip:         0.7000  ← Should be HIGH (>0.8)
# Osc:            0.6000  ← Should be HIGH (>0.8)
```

**Fixes:**

1. **Lower P_pp threshold** (simplest):
   ```bash
   python intelligent_client_ml_enhanced.py \
     --url http://localhost:8080 \
     --ppp-threshold 0.35  # Lower from 0.65
   ```
   - Allow detection of weaker patterns
   - Trade-off: May detect false positives

2. **Check HO event structure**:
   ```python
   # Edit intelligent_client_ml_enhanced.py
   # Add debug output in _extract_features() to print actual feature values:
   
   self._log(f"DEBUG {uid}: R_rev={r_rev:.3f}, D_flip={d_flip_norm:.3f}, Osc={osc:.3f}")
   ```
   - Verify features are calculated correctly
   - May reveal if HO events have wrong serving/target fields

---

### Possible Cause #3: HO Events Missing/Wrong Fields ⚠️⚠️⚠️
**Symptom:** HOs detected but feature extraction shows zeros

**Why it happens:**
- Handover events from simulator don't have correct `serving`/`target` fields
- Events have wrong field names (e.g., `from` instead of `serving`)
- Events incomplete

**Verify HO events:**
```bash
# Terminal 1: Start simulator
python app.py

# Terminal 2: Run setup
python setup_via_api.py

# Terminal 3: Check HO events
curl http://localhost:8080/api/get_state | python -c \
  "import sys, json; print(json.dumps(json.load(sys.stdin).get('handover_events', [])[-3:], indent=2))"

# Should show fields like:
# {
#   "ue_id": "UE-1",
#   "serving": "gNB-1",      ← ✅ Must have this
#   "target": "gNB-2",       ← ✅ Must have this
#   "rsrp": -85.0,
#   "time": 2.5,
#   "step": 25
# }
```

If **missing** `serving` or `target`, this is the bug!

---

## Recommended Fix Strategy

### Quick Fix (Try First)
1. Lower TTT to 1 step:
   ```bash
   curl -X POST http://localhost:8080/api/set_params \
     -H "Content-Type: application/json" \
     -d '{"ttt_steps": 1}'
   ```

2. Restart simulator and run client:
   ```bash
   python app.py  # Terminal 1
   python setup_via_api.py  # Terminal 2
   python intelligent_client_ml_enhanced.py \
     --url http://localhost:8080 \
     --ppp-threshold 0.4 \
     --verbose  # Terminal 3
   ```

3. Check if P_pp increases:
   - Expected: P_pp should now show 0.6-0.9 for UE-1 to UE-6

### Medium Fix (If Quick Fix Doesn't Work)
1. Run diagnostic:
   ```bash
   python check_ppp_diagnostic.py
   ```

2. Check output for which cause is active

3. Apply corresponding fix

### Deep Fix (If Medium Fix Doesn't Work)
1. Check HO events in API:
   ```bash
   curl http://localhost:8080/api/get_state | python -m json.tool | grep -A 50 "handover_events"
   ```

2. Verify fields are present and named correctly

3. If fields missing, trace back to [simulator_new.py](simulator_new.py#L385)

---

## Expected Behavior After Fix

**Before Fix:**
```
[11:39:39] [DEBUG] UE-1: HOs=3, P_pp=0.187 (threshold=0.65)
[11:39:39] [DEBUG] UE-2: HOs=3, P_pp=0.187 (threshold=0.65)
[11:39:39] [DEBUG] UE-3: HOs=3, P_pp=0.187 (threshold=0.65)
```

**After Fix (TTT=1, threshold=0.4):**
```
[11:39:45] [DEBUG] UE-1: HOs=12, P_pp=0.78 (threshold=0.4)  ← DETECTED ✅
[11:39:45] [DEBUG] UE-2: HOs=12, P_pp=0.78 (threshold=0.4)  ← DETECTED ✅
[11:39:45] [DEBUG] UE-3: HOs=12, P_pp=0.78 (threshold=0.4)  ← DETECTED ✅
[11:39:45] [OK] Anchor AnchorGNB-1 deployed @ (400,150) Score=2.34 Benefit=8.4
```

---

## Parameter Tuning Guide

### P_PP Threshold
- **Default**: 0.65 (conservative, may miss some ping-pong)
- **For synthetic patterns**: 0.35-0.50 (more aggressive detection)
- **For real networks**: Keep at 0.65-0.75 (fewer false positives)

**Command:**
```bash
python intelligent_client_ml_enhanced.py \
  --ppp-threshold 0.40  # Adjust as needed
```

### Sliding Window Size
- **Default**: 12 seconds (allows HO accumulation)
- **For fast movements**: 8-10 seconds (more responsive)
- **For slow movements**: 15-20 seconds (more HOs captured)

**Command:**
```bash
python intelligent_client_ml_enhanced.py \
  --window 15  # Adjust as needed
```

### TTT (Time-To-Trigger) Steps
- **Current**: 3 steps (~0.3s with default step size)
- **For 1-second position changes**: 1 step
- **For 10-second position changes**: 5-10 steps

**Command:**
```bash
curl -X POST http://localhost:8080/api/set_params \
  -H "Content-Type: application/json" \
  -d '{"ttt_steps": 1}'
```

### Hysteresis (dB)
- **Default**: Usually 2 dB
- **Lower** (1 dB): HOs trigger more easily
- **Higher** (3-4 dB): HOs trigger less frequently

**Command:**
```bash
curl -X POST http://localhost:8080/api/set_params \
  -H "Content-Type: application/json" \
  -d '{"hysteresis": 1}'
```

---

## Testing the Fix

### Step 1: Verify Diagnostic
```bash
python check_ppp_diagnostic.py > diagnostic_report.txt
cat diagnostic_report.txt
```

### Step 2: Apply Fix
```bash
# Example: Fix for TTT issue
curl -X POST http://localhost:8080/api/set_params \
  -H "Content-Type: application/json" \
  -d '{"ttt_steps": 1, "hysteresis": 1}'
```

### Step 3: Run ML Client
```bash
python intelligent_client_ml_enhanced.py \
  --url http://localhost:8080 \
  --ppp-threshold 0.40 \
  --window 15 \
  --verbose
```

### Step 4: Check Results
```bash
# Look for:
# [HH:MM:SS] UE-1: HOs=X, P_pp=Y
# Should show: X > 5, Y > 0.40 for UE-1 to UE-6

# Check if anchors deployed:
# [HH:MM:SS] [OK] Anchor AnchorGNB-1 deployed
```

---

## If Still Not Working

### Enable Verbose Logging
```bash
python intelligent_client_ml_enhanced.py \
  --url http://localhost:8080 \
  --verbose 2>&1 | tee client_debug.log
```

### Check Server Side
```bash
# Ensure simulator is generating HOs
curl http://localhost:8080/api/get_state | \
  python -c "import sys, json; data=json.load(sys.stdin); \
  print(f'HO Events: {len(data.get(\"handover_events\", []))}'); \
  print(f'Sim Time: {data.get(\"sim_time\", 0)}')"
```

### Manually Trace HO Pattern
```python
import requests
import json

state = requests.get("http://localhost:8080/api/get_state").json()

# Check UE-1 HO pattern
hos_ue1 = [h for h in state.get("handover_events", []) if h.get("ue_id") == "UE-1"]
for h in hos_ue1[-5:]:
    print(f"  {h.get('serving')} → {h.get('target')}")

# If all same: A → A (no HOs), that's the problem
# If pattern: A → B → C → D (random), that's normal
# If pattern: A → B → A → B (alternating), that's ping-pong ✅
```

---

## Summary

| Issue | Symptom | Fix | Expected Result |
|-------|---------|-----|-----------------|
| Low TTT | HOs=3, slow HOs | Set `ttt_steps=1` | HOs increase, P_pp increases |
| Threshold too high | P_pp=0.2, below threshold | Lower to 0.40 | UEs detected as candidates |
| Features wrong | Feature values low | Debug `_extract_features()` | Features match pattern |
| Model mismatch | Features high but P_pp low | Retrain on synthetic data | Model outputs realistic P_pp |

**Most likely fix:** Reduce TTT to 1 step + lower threshold to 0.40 ✅
