# 5G Simulator Server - ML Client Integration Guide

## Overview
The server now fully supports the ML-Enhanced Intelligent Detector client (`intelligent_client_ml_enhanced.py`).

---

## ✅ Complete API Endpoints for ML Client

### 1. **GET /api/get_state**
Returns complete simulator state including all data the ML client needs.

**Response includes:**
```json
{
  "running": boolean,
  "step": integer,
  "sim_time": float,
  "scenario": string,
  "gnbs": {
    "gNB-1": {
      "id": "gNB-1",
      "x": float, "y": float,
      "tx_power_dbm": integer,
      "num_sectors": integer,
      "is_anchor": boolean,
      "connected_ues": [list of UE IDs],
      ...
    }
  },
  "ues": {
    "UE-1": {
      "id": "UE-1",
      "x": float, "y": float,
      "serving": "gNB-1",          # ✅ ML client uses this
      "serving_gnb": "gNB-1",       # Also available for compatibility
      "target_gnb": "gNB-2",        # ✅ Current HO target (if in HO)
      "rsrp": float,
      "sinr": float,
      "dc_enabled": boolean,
      "anchor_gnb_id": string,
      ...
    }
  },
  "handover_events": [
    {
      "ue_id": "UE-1",
      "serving": "gNB-1",           # ✅ Serving gNB before HO
      "target": "gNB-2",            # ✅ Target gNB after HO
      "from": "gNB-1",
      "time": float,
      "step": integer,
      "rsrp": float,
      "sinr": float,
      "reason": string,
      "ping_pong": boolean,
      ...
    }
  ],
  "metrics": [...],
  "event_log": [...]
}
```

### 2. **POST /api/deploy_anchor** ⭐ NEW
Deploy a new AnchorGNB at specified canvas position (called by ML detector).

**Request:**
```json
{
  "x": 400.0,              # Canvas X position
  "y": 300.0,              # Canvas Y position
  "tx_power": 50,          # TX power in dBm (default: 50)
  "num_sectors": 6,        # Number of sectors (default: 6)
  "is_anchor": true,       # Mark as anchor
  "triggered_by": "UE-1,UE-2",  # Which UEs triggered deployment
  "ho_count": 5            # Number of HOs that triggered it
}
```

**Response:**
```json
{
  "success": true,
  "gnb_id": "AnchorGNB-1",
  "anchor_gnb_id": "AnchorGNB-1",
  "message": "AnchorGNB-1 deployed at (400,300)"
}
```

### 3. **POST /api/assign_dc** ⭐ NEW
Assign a UE to dual connectivity (DC) with an AnchorGNB.

**Request:**
```json
{
  "ue_id": "UE-1",
  "anchor_gnb_id": "AnchorGNB-1"
}
```

**Response:**
```json
{
  "success": true,
  "message": "UE-1 assigned to anchor AnchorGNB-1",
  "ue_id": "UE-1",
  "anchor_gnb_id": "AnchorGNB-1"
}
```

**Effect:**
- Sets `ue.dc_enabled = True`
- Sets `ue.anchor_gnb_id = anchor_gnb_id`
- UE will lock to anchor and won't perform normal handovers (see simulator_new.py line 333-348)

### 4. **POST /api/detector_status** ⭐ ENHANCED
Update detector status metrics (called by ML detector periodically).

**Request:**
```json
{
  "evaluation_steps": 100,
  "active_anchors": ["AnchorGNB-1", "AnchorGNB-2"],
  "cost_benefit_rejections": 5,
  "ue_count": 10,
  "errors": 0,
  "dc_assignments": 3,
  "dc_smart_skipped": 2,
  "hos_avoided": 15,
  "figures_saved": 8
}
```

**Response:**
```json
{
  "success": true,
  "message": "Detector status updated",
  "status": { ...current status... }
}
```

---

## 🔧 Fixes Applied

### 1. **Missing `/api/deploy_anchor` Endpoint**
- ❌ **Before:** Client called endpoint that didn't exist
- ✅ **After:** New endpoint wraps `simulator.add_anchor_gnb()` logic
- **File:** app.py (added new route)

### 2. **Missing `/api/assign_dc` Endpoint**
- ❌ **Before:** Client called endpoint that didn't exist
- ✅ **After:** New endpoint enables dual connectivity on UEs
- **File:** app.py (added new route)

### 3. **UE State Field Mismatch**
- ❌ **Before:** UE returned `serving_gnb` but client expected `serving`
- ✅ **After:** Both fields returned for compatibility
- **File:** simulation/ue_new.py (updated `to_dict()`)

### 4. **Missing `target_gnb` in UE State**
- ❌ **Before:** No indication of current HO target in UE state
- ✅ **After:** Returns `ttt_target` as `target_gnb` when UE is in handover
- **File:** simulation/ue_new.py (added field to `to_dict()`)

### 5. **Detector Status Endpoint**
- ❌ **Before:** Endpoint didn't read POST data, just returned status
- ✅ **After:** Properly handles POST with all ML client fields
- **File:** app.py (enhanced `/api/detector_status` route)

---

## 🚀 Why Client Can Now Detect HOs

### Before (Issues):
1. **Missing endpoints** → API calls failed → No feedback loop
2. **Field mismatch** → `serving` vs `serving_gnb` → Feature extraction failed
3. **No anchor support** → Couldn't deploy anchors → No DC enabled

### After (Fixed):
1. ✅ **Complete endpoint coverage** → All API calls work
2. ✅ **Proper field names** → ML client can extract features correctly
3. ✅ **Handover events** → Include all required fields:
   - `ue_id`, `serving`, `target`, `time`, `step`, `rsrp`, `sinr`
4. ✅ **Anchor deployment** → Works via `/api/deploy_anchor`
5. ✅ **DC assignment** → Works via `/api/assign_dc`

---

## 📊 Handover Event Fields (Verified)

From `simulator_new.py` line 385:
```python
ev = ue.trigger_handover(target_id, old_id, reason=reason)
ev.update({'time': self.sim_time, 'step': self.step, 'ue_id': ue.id, 'serving': old_id})
```

**Complete Event Structure:**
| Field | Source | Value |
|-------|--------|-------|
| `ue_id` | Updated at L385 | UE identifier |
| `serving` | Updated at L385 | Old gNB (source of HO) |
| `target` | trigger_handover() | New gNB (destination) |
| `from` | trigger_handover() | Same as `serving` |
| `time` | Updated at L385 | Simulation time |
| `step` | Updated at L385 | Simulation step |
| `rsrp` | trigger_handover() | RSRP at HO time |
| `sinr` | trigger_handover() | SINR at HO time |
| `reason` | trigger_handover() | HO reason (A3, ANCHOR_LOCK) |
| `ping_pong` | Set at L386 | Indicates ping-pong HO |

---

## 🔍 ML Client Data Flow

```
1. Client: GET /api/get_state
   ↓
2. Server: Returns state with:
   - handover_events (with serving, target, ue_id, rsrp, time)
   - ues (with serving, target_gnb, x, y, rsrp, dc_enabled)
   - gnbs (with x, y, is_anchor)
   ↓
3. Client: Ingests HOs → Extracts features → Scores UEs
   ↓
4. Client: If P_pp ≥ threshold:
   a. POST /api/deploy_anchor
   b. POST /api/assign_dc
   ↓
5. Server: Deploys anchor → Enables DC → Locks UE to anchor
   ↓
6. Simulator: UE stops ping-ponging (HO logic at line 333)
   ↓
7. Client: POST /api/detector_status (report metrics)
```

---

## ✨ Key Points

1. **Handover Detection Works**: Handover events have all required fields
2. **Feature Extraction Works**: UE state has correct field names
3. **Anchor Deployment Works**: `/api/deploy_anchor` creates new anchors
4. **DC Assignment Works**: `/api/assign_dc` enables dual connectivity
5. **Feedback Loop Works**: `/api/detector_status` accepts metrics

---

## 🧪 Testing the Integration

```bash
# Terminal 1: Start simulator
python app.py

# Terminal 2: Setup scenario
python setup_via_api.py

# Terminal 3: Run ML client
python intelligent_client_ml_enhanced.py \
  --url http://localhost:8080 \
  --ppp-threshold 0.65 \
  --visualize
```

Check the ML client output for:
- ✅ "HOs=" messages showing detection
- ✅ "P_pp=" showing ML predictions
- ✅ "Anchor gNB-X deployed" messages
- ✅ "Assigned to Anchor" DC assignments

---

## 📝 Summary

**Server now provides:**
- ✅ Complete state data with proper field names
- ✅ `/api/deploy_anchor` for anchor deployment
- ✅ `/api/assign_dc` for dual connectivity
- ✅ `/api/detector_status` for status reporting
- ✅ Handover events with all required features

**Client can now:**
- ✅ Detect handovers via state.handover_events
- ✅ Extract ML features from HO events
- ✅ Score UEs for ping-pong probability
- ✅ Deploy anchors to stop ping-ponging
- ✅ Report metrics and feedback
