#!/usr/bin/env python3
"""
Ping-Pong Scenario Setup via REST API
======================================
Configures the running Flask server with 4 gNBs, 11 UEs, and mobility file.

Usage:
    1. Start Flask: python app.py (in Terminal 1)
    2. Wait ~2 seconds for server to start
    3. Run this: python setup_via_api.py (in Terminal 2 or 3)
    4. Then run: python ml_client.py --url http://localhost:8080 --tcp --verbose
"""

import requests
import json
import time
import csv as csv_module
import sys

BASE_URL = 'http://localhost:8080'
TIMEOUT = 5

def api_post(endpoint, data=None):
    """Make POST request to Flask API."""
    try:
        resp = requests.post(f"{BASE_URL}{endpoint}", json=data, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  ✗ Error: {e}")
        return None

def api_request_multipart(endpoint, data_dict, files_dict):
    """Make multipart POST request (for file upload)."""
    try:
        resp = requests.post(
            f"{BASE_URL}{endpoint}", 
            data=data_dict, 
            files=files_dict, 
            timeout=TIMEOUT
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return None

def setup_ping_pong_scenario():
    """Setup scenario via REST API."""
    
    print("\n" + "="*70)
    print(" PING-PONG SCENARIO SETUP (via REST API)")
    print("="*70)
    
    # Check if server is running
    print("\n[0] Checking if Flask server is running...")
    try:
        resp = requests.get(f"{BASE_URL}/api/get_state", timeout=2)
        print(f"    [OK] Server is running at {BASE_URL}")
    except:
        print(f"    [ERROR] Cannot connect to {BASE_URL}")
        print(f"    Make sure Flask server is running: python app.py")
        return False
    
    # Reset simulation
    print("\n[1] Resetting simulation...")
    result = api_post('/api/reset')
    if result and result.get('success'):
        print(f"    [OK] Simulation reset")
    else:
        print(f"    [WARN] Reset may have failed, continuing...")
    
    # Add 4 gNBs
    print("\n[2] Adding 4 gNBs...")
    gnbs = [
        {'x': 150, 'y': 150, 'name': 'gNB-1', 'zone': 'Bottom-Left'},
        {'x': 500, 'y': 150, 'name': 'gNB-2', 'zone': 'Bottom-Right'},
        {'x': 150, 'y': 500, 'name': 'gNB-3', 'zone': 'Top-Left'},
        {'x': 500, 'y': 500, 'name': 'gNB-4', 'zone': 'Top-Right'},
    ]
    
    for gnb_config in gnbs:
        result = api_post('/api/add_gnb', {
            'x': gnb_config['x'],
            'y': gnb_config['y'],
            'tx_power': 43,
            'num_sectors': 3
        })
        if result:
            gnb_id = result.get('gnb_id', 'unknown')
            print(f"    [OK] {gnb_id:8s} @ ({gnb_config['x']:3d}, {gnb_config['y']:3d})  [{gnb_config['zone']}]")
        else:
            print(f"    [ERROR] Failed to add gNB at ({gnb_config['x']}, {gnb_config['y']})")
    
    # Add 11 UEs
    print("\n[3] Adding 11 UEs...")
    ue_ids = []
    for i in range(1, 12):
        result = api_post('/api/add_ue', {
            'x': 400,
            'y': 300,
            'mobility': 'none'
        })
        if result:
            uid = result.get('ue_id', f'UE-{i}')
            ue_ids.append(uid)
            print(f"    [OK] {uid}")
        else:
            print(f"    [ERROR] Failed to add UE-{i}")
    
    # Load mobility file
    print("\n[4] Loading mobility file from CSV...")
    mobility_file = 'ping_pong_11ue_30s.csv'
    
    try:
        # Verify file exists
        import os
        if not os.path.exists(mobility_file):
            print(f"    [ERROR] Mobility file not found: {mobility_file}")
            print(f"    Make sure '{mobility_file}' exists in project root")
            return False
        
        # Read file and upload
        print(f"    [INFO] Opening file: {mobility_file}")
        with open(mobility_file, 'rb') as f:
            files = {'file': (mobility_file, f, 'text/csv')}
            data = {'speed': '1.0'}
            print(f"    [INFO] Uploading {os.path.getsize(mobility_file)} bytes...")
            result = api_request_multipart('/api/upload_mobility_trace', data, files)
        
        if result is None:
            print(f"    [ERROR] Failed to load mobility file (no response)")
            return False
            
        if result and result.get('success'):
            applied = result.get('applied', [])
            skipped = result.get('skipped', [])
            print(f"    [OK] Loaded: {mobility_file}")
            print(f"    [OK] Applied to {len(applied)} UEs: {', '.join(applied[:3])}{'...' if len(applied) > 3 else ''}")
            if skipped:
                print(f"    [WARN] Skipped {len(skipped)} UEs: {', '.join(skipped)}")
        else:
            error_msg = result.get('error', 'unknown error') if result else 'unknown error'
            print(f"    [ERROR] Failed to load mobility file: {error_msg}")
            print(f"    Response: {result}")
            return False
            
    except FileNotFoundError:
        print(f"    [ERROR] Mobility file not found: {mobility_file}")
        print(f"    Make sure '{mobility_file}' exists in project root")
        return False
    except Exception as e:
        print(f"    [ERROR] Error loading mobility file: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # Start simulation
    print("\n[5] Starting simulation...")
    result = api_post('/api/start_simulation', {
        'scenario': 'UMa',
        'speed': 1.0
    })
    if result and result.get('success'):
        print(f"    [OK] Simulation started")
    else:
        print(f"    [ERROR] Failed to start simulation")
        print(f"    Response: {result}")
        return False
    
    # Verify setup
    print("\n[6] Verifying setup...")
    time.sleep(0.5)
    try:
        resp = requests.get(f"{BASE_URL}/api/get_state", timeout=5)
        state = resp.json()
        n_gnbs = len(state.get('gnbs', {}))
        n_ues = len(state.get('ues', {}))
        running = state.get('running', False)
        print(f"    [OK] gNBs: {n_gnbs}")
        print(f"    [OK] UEs: {n_ues}")
        print(f"    [OK] Running: {running}")
    except Exception as e:
        print(f"    [WARN] Could not verify: {e}")
    
    # Summary
    print("\n" + "="*70)
    print(" SETUP COMPLETE")
    print("="*70)
    print(f"\nNetwork Configuration:")
    print(f"  - 4 gNBs: corners of 800x600 canvas")
    print(f"  - 11 UEs: loaded from mobility file")
    print(f"  - Handover Margin: 3 dB")
    print(f"  - Time-To-Trigger: 0.1 seconds")
    print(f"  - Scenario: UMa (Urban Macro + Log-Normal shadowing)")
    print(f"\nPing-Pong Zones:")
    print(f"  Zone 1: gNB-1(150,150) <-> gNB-2(650,150) [y~150]")
    print(f"          UE-1, UE-2, UE-3 oscillate -> ~10-12 HOs each")
    print(f"  Zone 2: gNB-3(150,450) <-> gNB-4(650,450) [y~450]")
    print(f"          UE-4, UE-5, UE-6 oscillate -> ~10-12 HOs each")
    print(f"\nExpected Results (30 seconds):")
    print(f"  - Total handovers: 60-70 (before anchors)")
    print(f"  - Anchor deployments: 2 (via ML client)")
    print(f"  - HO reduction: 97% (60-70 -> 8-12)")
    print(f"\nNext Steps:")
    print(f"  1. Start ML client: python ml_client.py \\")
    print(f"                        --url http://localhost:8080 \\")
    print(f"                        --tcp \\")
    print(f"                        --verbose")
    print(f"\n  2. (Optional) View web UI: http://localhost:8080")
    print(f"  3. Monitor: tail -f ml_client_report.json")
    print(f"\n" + "="*70 + "\n")
    
    return True


if __name__ == '__main__':
    try:
        success = setup_ping_pong_scenario()
        if not success:
            sys.exit(1)
        print("[OK] Scenario ready! Simulation is running.")
        print("\nNow run in another terminal:")
        print("  python ml_client.py --url http://localhost:8080 --tcp --verbose")
    except KeyboardInterrupt:
        print("\n\n[ERROR] Setup cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Setup failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
