#!/bin/bash
slugs=(
  houston-s-peachtree houston-s-west-paces houston-s-bergen-county
  houston-s-boca-raton houston-s-irvine houston-s-saint-charles
  houston-s-north-miami-beach houston-s-pasadena houston-s-pompano-beach
  houston-s-scottsdale
  hillstone-coral-gables hillstone-park-cities hillstone-denver
  hillstone-houston hillstone-park-avenue hillstone-phoenix
  hillstone-embarcadero hillstone-santa-monica hillstone-winter-park
  palm-beach-grill gulfstream-newport bandera-corona-del-mar
  south-beverly-grill cherry-creek-grill rutherford-grill
  los-altos-grill east-hampton-grill woodmont-grill
  honor-bar-highland-park
)

echo "{"
first=true
for slug in "${slugs[@]}"; do
  resp=$(curl -s "https://loyaltyapi.wisely.io/v2/web/reservations/merchant?slug=$slug" \
    -H 'Origin: https://reservations.getwisely.com' \
    -H 'Referer: https://reservations.getwisely.com/')
  id=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null)
  name=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('name',''))" 2>/dev/null)
  if [ -n "$id" ]; then
    [ "$first" = true ] && first=false || echo ","
    printf '  "%s": {"id": %s, "name": "%s"}' "$slug" "$id" "$name"
    echo "  ✅ $slug: $id ($name)" >&2
  else
    echo "  ❌ $slug: not found" >&2
  fi
done
echo ""
echo "}"
