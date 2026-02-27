#!/bin/bash

echo "Starting KEPCO Power Planner add-on"

# Read configuration
ACCOUNTS=$(jq --compact-output '.accounts' /data/options.json)
UPDATE_INTERVAL_MINUTES=$(jq --raw-output '.update_interval' /data/options.json)
MQTT_HOST=$(jq --raw-output '.mqtt_host' /data/options.json)
MQTT_PORT=$(jq --raw-output '.mqtt_port' /data/options.json)
MQTT_USERNAME=$(jq --raw-output '.mqtt_username' /data/options.json)
MQTT_PASSWORD=$(jq --raw-output '.mqtt_password' /data/options.json)

# Export for the python script
export ACCOUNTS="${ACCOUNTS}"
export MQTT_HOST="${MQTT_HOST}"
export MQTT_PORT="${MQTT_PORT}"
export MQTT_USERNAME="${MQTT_USERNAME}"
export MQTT_PASSWORD="${MQTT_PASSWORD}"

# Convert interval to seconds
UPDATE_INTERVAL_SECONDS=$((UPDATE_INTERVAL_MINUTES * 60))

# Main loop
while true; do
  echo "Running KEPCO scrape job..."
  python3 /app/main.py

  echo "Next run in ${UPDATE_INTERVAL_MINUTES} minutes."
  sleep ${UPDATE_INTERVAL_SECONDS}
done
