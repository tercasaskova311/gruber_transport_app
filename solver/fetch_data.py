"""Download all 4 scenarios into data/<scenario>/ in the format run.py expects.
Usage:  python fetch_data.py
"""
import os
import urllib.request

BASE = "https://hackathon-challenge.gruber-logistics.dev/Hackaton2026/Scenarios"
SCENARIOS = ["scenario_small", "scenario_middle", "scenario_big", "scenario_competitive"]
ENDPOINTS = [("Cities", "cities"), ("Trucks", "trucks"), ("Orders", "orders"),
             ("DistanceMatrix", "distance_matrix")]

for sc in SCENARIOS:
    folder = os.path.join("data", sc)
    os.makedirs(folder, exist_ok=True)
    for ep, name in ENDPOINTS:
        data = urllib.request.urlopen(f"{BASE}/{sc}/{ep}").read()
        with open(os.path.join(folder, f"{name}.json"), "wb") as f:
            f.write(data)
    print("saved", sc)
