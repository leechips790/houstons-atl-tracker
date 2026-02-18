import subprocess, json, re

slugs = [
    "houston-s-peachtree", "houston-s-west-paces", "houston-s-bergen-county",
    "houston-s-boca-raton", "houston-s-irvine", "houston-s-saint-charles",
    "houston-s-north-miami-beach", "houston-s-pasadena", "houston-s-pompano-beach",
    "houston-s-scottsdale",
    "hillstone-coral-gables", "hillstone-park-cities", "hillstone-denver",
    "hillstone-houston", "hillstone-park-avenue", "hillstone-phoenix",
    "hillstone-embarcadero", "hillstone-santa-monica", "hillstone-winter-park",
    "palm-beach-grill", "gulfstream-newport", "bandera-corona-del-mar",
    "south-beverly-grill", "cherry-creek-grill", "rutherford-grill",
    "los-altos-grill", "east-hampton-grill", "woodmont-grill",
    "honor-bar-highland-park"
]

results = {}
for slug in slugs:
    url = f"https://reservations.getwisely.com/{slug}"
    try:
        r = subprocess.run(["curl", "-s", "-L", url], capture_output=True, text=True, timeout=15)
        html = r.stdout
        # Look for merchant id in the page source
        # Wisely embeds config as JSON in script tags
        m = re.search(r'"merchant_id"\s*:\s*(\d+)', html)
        if not m:
            m = re.search(r'"id"\s*:\s*(\d+)', html)
        if m:
            results[slug] = int(m.group(1))
            print(f"✅ {slug}: {m.group(1)}")
        else:
            # Try finding preloaded state
            m2 = re.search(r'merchant.*?"id"\s*:\s*(\d+)', html)
            if m2:
                results[slug] = int(m2.group(1))
                print(f"✅ {slug}: {m2.group(1)}")
            else:
                print(f"❌ {slug}: no merchant_id found")
                results[slug] = None
    except Exception as e:
        print(f"❌ {slug}: {e}")
        results[slug] = None

with open("wisely_merchants.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"\nDone. {sum(1 for v in results.values() if v)} / {len(results)} found")
