import os
import json
import time
import requests
import paho.mqtt.client as mqtt
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import NoSuchElementException, TimeoutException, NoAlertPresentException

# --- MQTT Configuration (auto-discovered via Supervisor API) ---
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN")
if not SUPERVISOR_TOKEN:
    raise ValueError("SUPERVISOR_TOKEN environment variable not set.")

MQTT_DISCOVERY_PREFIX = "homeassistant"

def get_mqtt_config():
    """Fetches MQTT connection details from the HA Supervisor service discovery API."""
    url = "http://supervisor/services/mqtt"
    headers = {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    data = response.json().get("data", {})
    return {
        "host": data.get("host", "core-mosquitto"),
        "port": int(data.get("port", 1883)),
        "username": data.get("username", ""),
        "password": data.get("password", ""),
        "ssl": data.get("ssl", False),
    }

def create_mqtt_client():
    config = get_mqtt_config()
    print(f"Connecting to MQTT broker at {config['host']}:{config['port']}")
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if config["username"]:
        client.username_pw_set(config["username"], config["password"])
    if config["ssl"]:
        client.tls_set()
    client.connect(config["host"], config["port"], keepalive=60)
    return client

def publish_discovery(client, cust_no, sensor_type, config):
    """Publishes MQTT Discovery config message for a sensor."""
    unique_id = f"kepco_{cust_no}_{sensor_type}"
    state_topic = f"kepco/{cust_no}/{sensor_type}"
    discovery_topic = f"{MQTT_DISCOVERY_PREFIX}/sensor/{unique_id}/config"

    payload = {
        "name": f"{config['name']} ({cust_no})",
        "unique_id": unique_id,
        "state_topic": state_topic,
        "unit_of_measurement": config["unit"],
        "device_class": config["device_class"],
        "icon": config["icon"],
        "device": {
            "identifiers": [f"kepco_{cust_no}"],
            "name": f"한전 파워플래너 ({cust_no})",
            "manufacturer": "KEPCO",
            "model": "Power Planner",
        },
    }
    client.publish(discovery_topic, json.dumps(payload), retain=True)

def publish_state(client, cust_no, sensor_type, state):
    """Publishes sensor state to MQTT."""
    state_topic = f"kepco/{cust_no}/{sensor_type}"
    client.publish(state_topic, str(state), retain=True)

SENSOR_CONFIGS = {
    "realtime_usage":              {"name": "실시간 사용량",     "unit": "kWh", "icon": "mdi:flash",             "device_class": "energy"},
    "predicted_usage":             {"name": "예상 사용량",       "unit": "kWh", "icon": "mdi:flash-alert",        "device_class": "energy"},
    "realtime_fee":                {"name": "실시간 요금",       "unit": "원",  "icon": "mdi:cash",               "device_class": "monetary"},
    "predicted_fee":               {"name": "예상 요금",         "unit": "원",  "icon": "mdi:cash-multiple",      "device_class": "monetary"},
    "generation_amount":           {"name": "발전량",            "unit": "kWh", "icon": "mdi:solar-power",        "device_class": "energy"},
    "net_realtime_charge":         {"name": "상계 후 요금",      "unit": "원",  "icon": "mdi:cash-minus",         "device_class": "monetary"},
    "net_usage_after_compensation":{"name": "상계 후 사용량",    "unit": "kWh", "icon": "mdi:transmission-tower", "device_class": "energy"},
}

def create_sensor_set(client, cust_no, sensor_data):
    """Publishes discovery config and state for all sensors of a customer."""
    ha_sensor_data = {
        "realtime_usage":               sensor_data.get("realtime_usage"),
        "predicted_usage":              sensor_data.get("estimated_usage"),
        "realtime_fee":                 sensor_data.get("realtime_charge"),
        "predicted_fee":                sensor_data.get("estimated_charge"),
        "generation_amount":            sensor_data.get("generation_amount"),
        "net_realtime_charge":          sensor_data.get("net_realtime_charge"),
        "net_usage_after_compensation": sensor_data.get("net_usage_after_compensation"),
    }

    for sensor_type, state in ha_sensor_data.items():
        if state is not None and sensor_type in SENSOR_CONFIGS:
            config = SENSOR_CONFIGS[sensor_type]
            publish_discovery(client, cust_no, sensor_type, config)
            publish_state(client, cust_no, sensor_type, state)
            print(f"Published sensor: kepco_{cust_no}_{sensor_type} = {state}")

# --- Selenium Scraping Logic ---
ACCOUNTS_JSON = os.environ.get("ACCOUNTS")
if not ACCOUNTS_JSON:
    raise ValueError("ACCOUNTS environment variable not set.")
ACCOUNTS = json.loads(ACCOUNTS_JSON)

def scrape_customer_data(driver, wait):
    """Scrapes all relevant data for the currently selected customer."""
    wait.until(lambda d: d.find_element(By.ID, "F_AP_QT").text.strip() != "")
    wait.until(lambda d: d.find_element(By.ID, "PREDICT_TOT").text.strip() != "")
    wait.until(lambda d: d.find_element(By.ID, "TOTAL_CHARGE").text.strip() != "")
    wait.until(lambda d: d.find_element(By.ID, "PREDICT_TOTAL_CHARGE").text.strip() != "")

    max_retries = 5
    sensor_data = {}

    for i in range(max_retries):
        try:
            realtime_usage  = float(driver.find_element(By.ID, "F_AP_QT").text.replace('kWh', '').replace(',', '').strip())
            estimated_usage = float(driver.find_element(By.ID, "PREDICT_TOT").text.replace('kWh', '').replace(',', '').strip())
            realtime_charge  = int(driver.find_element(By.ID, "TOTAL_CHARGE").text.replace('원', '').replace(',', '').strip())
            estimated_charge = int(driver.find_element(By.ID, "PREDICT_TOTAL_CHARGE").text.replace('원', '').replace(',', '').strip())

            usage_same  = (realtime_usage == estimated_usage)
            charge_same = (realtime_charge == estimated_charge)

            if usage_same == charge_same:
                sensor_data["realtime_usage"]  = realtime_usage
                sensor_data["estimated_usage"] = estimated_usage
                sensor_data["realtime_charge"]  = realtime_charge
                sensor_data["estimated_charge"] = estimated_charge
                break

            if i < max_retries - 1:
                time.sleep(1)
        except (ValueError, NoSuchElementException):
            if i < max_retries - 1:
                time.sleep(1)
            else:
                print("Could not parse main page data after retries.")
                return None

    if not sensor_data:
        print("Failed to get consistent main page data.")
        return None

    try:
        driver.get("https://pp.kepco.co.kr/pr/pr0201.do?menu_id=O020401")
        wait.until(EC.presence_of_element_located((By.CLASS_NAME, "smart_now")))

        thead = driver.find_element(By.CSS_SELECTOR, "div.smart_now thead")
        if len(thead.find_elements(By.TAG_NAME, 'tr')) > 0:
            power_rate_row = driver.find_element(By.XPATH, "//th[contains(text(), '전력량요금')]/..")
            last_td = power_rate_row.find_elements(By.TAG_NAME, 'td')[-1]
            net_usage = float(last_td.text.replace('kWh', '').strip().replace(',', ''))

            sensor_data["net_usage_after_compensation"] = round(sensor_data["realtime_usage"] - net_usage, 3)
            sensor_data["generation_amount"] = round(net_usage, 3)

            charge_row = driver.find_element(By.XPATH, "//tfoot//th[contains(text(), '실시간 요금')]/..")
            last_charge_td = charge_row.find_elements(By.TAG_NAME, 'td')[-1]
            sensor_data["net_realtime_charge"] = int(last_charge_td.text.replace('원', '').replace(',', '').strip())
    except (NoSuchElementException, IndexError, ValueError, TimeoutException) as e:
        print(f"Could not find generation data, skipping. Error: {e}")
    finally:
        driver.back()
        wait.until(EC.presence_of_element_located((By.ID, "country_id")))

    return sensor_data


# --- Main Execution ---
mqtt_client = create_mqtt_client()
mqtt_client.loop_start()

try:
    for account in ACCOUNTS:
        RSA_USER_ID = account.get("RSA_USER_ID")
        RSA_USER_PWD = account.get("RSA_USER_PWD")

        if not RSA_USER_ID or not RSA_USER_PWD:
            print("Skipping account due to missing ID or PWD.")
            continue

        print(f"Processing account: {RSA_USER_ID}")

        chrome_options = Options()
        chrome_options.add_argument("--headless=new")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-software-rasterizer")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

        service = Service(executable_path='/usr/bin/chromedriver')
        driver = webdriver.Chrome(service=service, options=chrome_options)

        try:
            print("Starting KEPCO scrape job...")
            driver.get("https://pp.kepco.co.kr/")
            wait = WebDriverWait(driver, 20)

            wait.until(EC.presence_of_element_located((By.ID, "RSA_USER_ID"))).send_keys(RSA_USER_ID)
            driver.find_element(By.ID, "RSA_USER_PWD").send_keys(RSA_USER_PWD)
            login_button = wait.until(EC.presence_of_element_located((By.ID, "intro_btn_indi")))
            driver.execute_script("arguments[0].click();", login_button)

            time.sleep(1)
            try:
                alert = driver.switch_to.alert
                alert_text = alert.text
                print(f"Login failed with alert: {alert_text}")
                alert.accept()
                continue
            except NoAlertPresentException:
                pass

            try:
                wait.until(EC.presence_of_element_located((By.ID, "country_id")))
                print("Logged in.")
            except TimeoutException:
                print("Login failed (no alert, but main page did not load).")
                continue

            cust_no_select = driver.find_element(By.ID, "country_id")
            cust_no_options = cust_no_select.find_elements(By.TAG_NAME, "option")
            customer_numbers = [opt.get_attribute("value") for opt in cust_no_options]
            print(f"Found customer numbers: {customer_numbers}")

            for i, cust_no in enumerate(customer_numbers):
                print("-" * 20)
                if i > 0:
                    print(f"Switching to customer number: {cust_no}")

                    cust_no_select = driver.find_element(By.ID, "country_id")
                    sb_value = cust_no_select.get_attribute("sb")
                    sb_holder_id = f"sbHolder_{sb_value}"
                    sb_options_id = f"sbOptions_{sb_value}"

                    sb_holder = wait.until(EC.element_to_be_clickable((By.ID, sb_holder_id)))
                    sb_holder.click()

                    wait.until(EC.visibility_of_element_located((By.XPATH, f"//ul[@id='{sb_options_id}']/li/a[@rel='{cust_no}']")))
                    option_link = wait.until(EC.presence_of_element_located((By.XPATH, f"//a[@rel='{cust_no}']")))
                    driver.execute_script("arguments[0].click();", option_link)

                    wait.until(lambda d: d.find_element(By.ID, "F_AP_QT").text.strip() != "")
                    time.sleep(2)

                print(f"Scraping data for customer number: {cust_no}")
                scraped_data = scrape_customer_data(driver, wait)
                if scraped_data:
                    create_sensor_set(mqtt_client, cust_no, scraped_data)
                    print(f"Successfully published sensors for {cust_no}")

        except Exception as e:
            print(f"An unexpected error occurred for account {RSA_USER_ID}: {e}")

        finally:
            driver.quit()
            print(f"Scrape job finished for account {RSA_USER_ID}.")

finally:
    mqtt_client.loop_stop()
    mqtt_client.disconnect()

print("All accounts processed.")
