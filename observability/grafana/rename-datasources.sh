#!/usr/bin/env bash
# Rename Grafana datasource UIDs in the edictum dashboard.
#
# The dashboard ships with generic UIDs (grafanacloud-prom / grafanacloud-traces)
# for the local Docker stack. If you're importing into Grafana Cloud, run this
# script to replace them with your instance-specific UIDs.
#
# Usage:
#   ./observability/grafana/rename-datasources.sh <prometheus-uid> <tempo-uid>
#
# Example (Grafana Cloud):
#   ./observability/grafana/rename-datasources.sh grafanacloud-myorg-prom grafanacloud-myorg-traces
#
# To find your UIDs: Grafana Cloud > Connections > Data sources > click each one > UID is in the URL.
#
# To revert to generic UIDs:
#   ./observability/grafana/rename-datasources.sh grafanacloud-prom grafanacloud-traces

set -euo pipefail

if [ $# -ne 2 ]; then
    echo "Usage: $0 <prometheus-uid> <tempo-uid>"
    echo ""
    echo "Example:"
    echo "  $0 grafanacloud-myorg-prom grafanacloud-myorg-traces"
    exit 1
fi

PROM_UID="$1"
TEMPO_UID="$2"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DASHBOARD="$SCRIPT_DIR/edictum-dashboard.json"

if [ ! -f "$DASHBOARD" ]; then
    echo "ERROR: Dashboard not found at $DASHBOARD"
    exit 1
fi

# Replace Prometheus UID (current generic or any previous value in the DS_PROMETHEUS variable)
sed -i.bak -E \
    "s/\"uid\": \"grafanacloud-[^\"]*-prom\"/\"uid\": \"$PROM_UID\"/g; \
     s/\"uid\": \"grafanacloud-prom\"/\"uid\": \"$PROM_UID\"/g" \
    "$DASHBOARD"

# Replace Tempo UID
sed -i.bak -E \
    "s/\"uid\": \"grafanacloud-[^\"]*-traces\"/\"uid\": \"$TEMPO_UID\"/g; \
     s/\"uid\": \"grafanacloud-traces\"/\"uid\": \"$TEMPO_UID\"/g" \
    "$DASHBOARD"

# Also fix the Explore link in the markdown panel
sed -i.bak -E \
    "s|datasourceUid=grafanacloud-[^&\"]*-traces|datasourceUid=$TEMPO_UID|g; \
     s|datasourceUid=grafanacloud-traces|datasourceUid=$TEMPO_UID|g" \
    "$DASHBOARD"

# Also update the template variable text/value fields
sed -i.bak -E \
    "s/\"text\": \"grafanacloud-[^\"]*-prom\"/\"text\": \"$PROM_UID\"/g; \
     s/\"value\": \"grafanacloud-[^\"]*-prom\"/\"value\": \"$PROM_UID\"/g; \
     s/\"text\": \"grafanacloud-prom\"/\"text\": \"$PROM_UID\"/g; \
     s/\"value\": \"grafanacloud-prom\"/\"value\": \"$PROM_UID\"/g; \
     s/\"text\": \"grafanacloud-[^\"]*-traces\"/\"text\": \"$TEMPO_UID\"/g; \
     s/\"value\": \"grafanacloud-[^\"]*-traces\"/\"value\": \"$TEMPO_UID\"/g; \
     s/\"text\": \"grafanacloud-traces\"/\"text\": \"$TEMPO_UID\"/g; \
     s/\"value\": \"grafanacloud-traces\"/\"value\": \"$TEMPO_UID\"/g" \
    "$DASHBOARD"

# Clean up backup files
rm -f "$DASHBOARD.bak"

echo "Updated datasource UIDs in edictum-dashboard.json:"
echo "  Prometheus: $PROM_UID"
echo "  Tempo:      $TEMPO_UID"
