# ⚡ Quick Reference - ML Client Integration

## 🔍 What Was Wrong

| Problem | Cause | Fix |
|---------|-------|-----|
| Client crashes on deploy | No `/api/deploy_anchor` endpoint | ✅ Added endpoint |
| Client crashes on DC assign | No `/api/assign_dc` endpoint | ✅ Added endpoint |
| HO feature extraction fails | UE returned `serving_gnb` not `serving` | ✅ Added `serving` alias |
| Target gNB tracking broken | No `target_gnb` in UE state | ✅ Added from `ttt_target` |
| Detector metrics ignored | Endpoint didn't read POST data | ✅ Enhanced to read payload |

---

## 📡 API Endpoints (Complete List)

### State & Metrics
- **GET** `/api/get_state` → Full simulator state ✅
- **GET** `/api/get_metrics` → Historical metrics
- **GET** `/api/get_handover_details` → HO list

### Anchor & DC Management  
- **POST** `/api/deploy_anchor` ⭐ NEW → Deploy AnchorGNB
- **POST** `/api/assign_dc` ⭐ NEW → Enable DC on UE
- **POST** `/api/detector_status` ⭐ ENHANCED → Report metrics

### Simulator Control
- **POST** `/api/start_simulation` → Start
- **POST** `/api/stop_simulation` → Stop
- **POST** `/api/reset` → Reset

### gNB/UE Management
- **POST** `/api/add_gnb` → Add gNB
- **POST** `/api/add_anchor_gnb` → Add anchor (old name)
- **POST** `/api/add_ue` → Add UE
- **POST** `/api/move_gnb` → Move gNB
- **POST** `/api/move_ue` → Move UE

---

## 🎯 Key Data Structures

### UE State (from `/api/get_state`)
```json
{
  "id": "UE-1",
  "x": 100.0,
  "y": 150.0,
  "serving": "gNB-1",        ✅ Use this (ML client)
  "serving_gnb": "gNB-1",    (also available)
  "target_gnb": "gNB-2",     ✅ Current HO target
  "rsrp": -85.0,
  "sinr": 8.5,
  "dc_enabled": false,
  "anchor_gnb_id": null
}
```

### Handover Event (from `/api/get_state`)
```json
{
  "ue_id": "UE-1",
  "serving": "gNB-1",        ✅ Source gNB
  "target": "gNB-2",         ✅ Destination gNB
  "from": "gNB-1",           (same as serving)
  "time": 2.5,
  "step": 25,
  "rsrp": -85.0,
  "sinr": 8.5,
  "reason": "A3",
  "ping_pong": false
}
```

### Deploy Anchor Request
```json
{
  "x": 400.0,
  "y": 300.0,
  "tx_power": 50,
  "num_sectors": 6,
  "triggered_by": "UE-1,UE-2",
  "ho_count": 5
}
```

### Assign DC Request  
```json
{
  "ue_id": "UE-1",
  "anchor_gnb_id": "AnchorGNB-1"
}
```

---

## ✨ ML Client Workflow

```
1️⃣  GET /api/get_state
    └─ Get UEs, gNBs, handover_events

2️⃣  Process handover_events
    └─ Extract features: f_HO, sigma2_RSRP, R_rev, D_flip, Osc

3️⃣  Score UE via ML model
    └─ P_pp = model.predict_proba(features)

4️⃣  If P_pp ≥ threshold:
    ├─ POST /api/deploy_anchor
    │  └─ Creates AnchorGNB at UE cluster centroid
    └─ POST /api/assign_dc  
       └─ Locks UE to anchor via dual connectivity

5️⃣  Simulator response:
    └─ UE.dc_enabled = True → stops HO logic → ping-pong stops

6️⃣  POST /api/detector_status
    └─ Report metrics
```

---

## 🚀 Running the Full Stack

```bash
# Terminal 1: Start server
python app.py
# Output: 5G NR Network Simulator running on http://localhost:8080

# Terminal 2: Setup scenario  
python setup_via_api.py
# Output: 4 gNBs + 10 UEs deployed, simulation started

# Terminal 3: Start ML detector
python intelligent_client_ml_enhanced.py \
  --url http://localhost:8080 \
  --ppp-threshold 0.65 \
  --visualize \
  --verbose

# Output should include:
# [00:00:00] [ModelLoader] Loaded trained model from pingpong_model.pkl
# [00:00:05] UE-1: HOs=5, P_pp=0.78 (threshold=0.65)
# [00:00:05] [OK] Anchor AnchorGNB-1 deployed @ (400,300) Score=1.95
```

---

## 🧪 Quick Test

```bash
# Test deployment endpoint
curl -X POST http://localhost:8080/api/deploy_anchor \
  -H "Content-Type: application/json" \
  -d '{
    "x": 400,
    "y": 300,
    "tx_power": 50,
    "num_sectors": 6,
    "triggered_by": "TEST",
    "ho_count": 0
  }'
# Should return: {"success": true, "gnb_id": "AnchorGNB-1", ...}

# Test DC assignment
curl -X POST http://localhost:8080/api/assign_dc \
  -H "Content-Type: application/json" \
  -d '{"ue_id": "UE-1", "anchor_gnb_id": "AnchorGNB-1"}'
# Should return: {"success": true, "message": "UE-1 assigned..."}

# Check state
curl http://localhost:8080/api/get_state | python -m json.tool
# Should show handover_events with serving/target fields
```

---

## 📊 Files Changed

| File | Lines | Changes |
|------|-------|---------|
| `app.py` | 265-318 | Added `/api/deploy_anchor` + `/api/assign_dc` + enhanced `/api/detector_status` |
| `simulation/ue_new.py` | 118-147 | Added `serving` alias + `target_gnb` field |

---

## ✅ Verification Steps

- [ ] Server starts: `python app.py` (no errors)
- [ ] Can GET state: `curl http://localhost:8080/api/get_state`
- [ ] Can deploy anchor: `curl -X POST http://localhost:8080/api/deploy_anchor ...`
- [ ] Can assign DC: `curl -X POST http://localhost:8080/api/assign_dc ...`
- [ ] ML client detects HOs: `python intelligent_client_ml_enhanced.py --url http://localhost:8080`
- [ ] UE state has `serving`, `target_gnb` fields
- [ ] Handover events have `serving`, `target`, `ue_id`, `rsrp`, `time` fields

---

## 📚 Full Documentation

- **SERVER_ML_CLIENT_INTEGRATION.md** - Complete API reference & data structures
- **HO_DETECTION_TROUBLESHOOTING.md** - Detailed root cause analysis
- **README_ML_ENHANCED.md** - ML client usage guide
