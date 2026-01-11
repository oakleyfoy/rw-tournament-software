"""Manual test of the conflict report endpoint"""

import requests

url = "http://localhost:8000/api/tournaments/1/schedule/conflicts?schedule_version_id=1"

print("=" * 80)
print(f"Testing GET {url}")
print("=" * 80)

try:
    response = requests.get(url)
    print(f"\nHTTP Status Code: {response.status_code}")
    print(f"Content-Type: {response.headers.get('Content-Type')}")

    if response.status_code == 200:
        data = response.json()
        print("\n[SUCCESS] Conflict Report Generated")
        print("\nSummary:")
        print(f"  - Tournament ID: {data['summary']['tournament_id']}")
        print(f"  - Schedule Version ID: {data['summary']['schedule_version_id']}")
        print(f"  - Total Slots: {data['summary']['total_slots']}")
        print(f"  - Total Matches: {data['summary']['total_matches']}")
        print(f"  - Assigned Matches: {data['summary']['assigned_matches']}")
        print(f"  - Unassigned Matches: {data['summary']['unassigned_matches']}")
        print(f"  - Assignment Rate: {data['summary']['assignment_rate']}%")

        print(f"\nUnassigned Matches: {len(data['unassigned'])}")
        if data["unassigned"]:
            print(
                f"  First unassigned: Match #{data['unassigned'][0]['match_id']} - Stage: {data['unassigned'][0]['stage']}, Reason: {data['unassigned'][0]['reason']}"
            )

        print("\nSlot Pressure:")
        print(f"  - Unused Slots: {data['slot_pressure']['unused_slots_count']}")
        print(f"  - Longest Match Duration: {data['slot_pressure']['longest_match_duration']} min")
        print(f"  - Max Slot Duration: {data['slot_pressure']['max_slot_duration']} min")

        print(f"\nStage Timeline: {len(data['stage_timeline'])} stages")
        for stage in data["stage_timeline"]:
            print(
                f"  - {stage['stage']}: {stage['assigned_count']} assigned, {stage['unassigned_count']} unassigned, spillover: {stage['spillover_warning']}"
            )

        print("\nOrdering Integrity:")
        print(f"  - Deterministic Order OK: {data['ordering_integrity']['deterministic_order_ok']}")
        print(f"  - Violations: {len(data['ordering_integrity']['violations'])}")
        if data["ordering_integrity"]["violations"]:
            for v in data["ordering_integrity"]["violations"][:3]:
                print(f"    * {v['type']}: Match {v['earlier_match_id']} vs {v['later_match_id']}")

    else:
        print("\n[FAILURE] Response body:")
        print(response.text[:500])

except Exception as e:
    print(f"\n[ERROR] {type(e).__name__}: {e}")

print("=" * 80)
