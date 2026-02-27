#!/bin/bash

echo "Starting KEPCO Power Planner add-on"

# Read configuration
ACCOUNTS=$(jq --compact-output '.accounts' /data/options.json)
UPDATE_INTERVAL_MINUTES=$(jq --raw-output '.update_interval' /data/options.json)

# Export for the python script
export ACCOUNTS="${ACCOUNTS}"

# Convert interval to seconds
UPDATE_INTERVAL_SECONDS=$((UPDATE_INTERVAL_MINUTES * 60))

# Main loop
while true; do
  echo "Running KEPCO scrape job..."
  python3 /app/main.py

  echo "Next run in ${UPDATE_INTERVAL_MINUTES} minutes."
  sleep ${UPDATE_INTERVAL_SECONDS}
done
