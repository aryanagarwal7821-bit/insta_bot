#!/usr/bin/env python3
"""
Final version — Insta Multi Bot
Author: Aryan + GPT5
Description:
Automates follower scraping & follow requests based on abbreviations in bios.
Reads everything from 'schools.xlsx' with per-school bot credentials.

Excel Columns Required:
  School Name | Instagram ID | Password | Abbreviation | Max follow per school | bot_username | bot_password

Usage:
  source venv/bin/activate
  python insta_multi_bot.py
"""

import os, time, random, csv, traceback, json
import pandas as pd
from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ========== CONFIG ==========
SCHOOLS_XLSX = "schools.xlsx"
PROGRESS_CSV = "bot_progress.csv"
DEBUG_LOG = "bot_debug.log"
DAILY_CAP = 300
DELAY_MIN = 2.0
DELAY_MAX = 5.0
SCROLL_DELAY = 1.2
FOLLOW_LOAD_FACTOR = 6
WAIT_FOR_CONTINUE_FILE = True
CONTINUE_WAIT_SECONDS = 600
# ============================

load_dotenv()
FALLBACK_USER = os.getenv("IG_USERNAME")
FALLBACK_PASS = os.getenv("IG_PASSWORD")

# ----------------- UTILITIES -----------------
def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(DEBUG_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")

def human_sleep(a=DELAY_MIN, b=DELAY_MAX):
    time.sleep(random.uniform(a, b))

# ----------------- DRIVER -----------------
def start_driver():
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=en-US")
    options.add_argument("--disable-blink-features=AutomationControlled")
    driver = uc.Chrome(options=options)
    time.sleep(3)  # give time for chrome to initialize
    try:
        driver.maximize_window()
    except:
        pass
    return driver

# ----------------- LOGIN -----------------
def login_with_checkpoint_support(driver, username, password):
    log(f"Attempting login for {username} ...")
    driver.get("https://www.instagram.com/accounts/login/")
    WebDriverWait(driver, 40).until(EC.presence_of_element_located((By.NAME, "username")))
    human_sleep(1,2)
    driver.find_element(By.NAME, "username").send_keys(username)
    driver.find_element(By.NAME, "password").send_keys(password)
    human_sleep(1,2)
    driver.find_element(By.NAME, "password").send_keys(Keys.ENTER)
    human_sleep(3,5)

    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//nav")))
        log("✅ Logged in successfully.")
        return True
    except:
        log("⚠️ 2FA/Checkpoint detected. Complete verification in Chrome.")
        if WAIT_FOR_CONTINUE_FILE:
            log("➡️ Create 'continue.txt' after verification.")
            waited = 0
            while waited < CONTINUE_WAIT_SECONDS:
                if os.path.exists("continue.txt"):
                    log("Detected continue.txt — verifying login...")
                    driver.get(f"https://www.instagram.com/{username}/")
                    try:
                        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.TAG_NAME, "header")))
                        os.remove("continue.txt")
                        log("✅ Verification complete.")
                        return True
                    except:
                        log("Still not verified, waiting...")
                time.sleep(2)
                waited += 2
            log("❌ Timeout waiting for verification.")
            return False
        else:
            return False

def safe_logout(driver):
    try:
        driver.get("https://www.instagram.com/accounts/logout/")
        human_sleep(2,3)
    except:
        pass

# ----------------- HELPERS -----------------
def parse_handles(cell):
    if pd.isna(cell): return []
    parts = [p.strip().lstrip("@") for p in str(cell).replace(";", ",").split(",") if p.strip()]
    return parts

def parse_abbreviations(cell):
    if pd.isna(cell): return []
    return [p.strip().lower() for p in str(cell).replace(";", ",").split(",") if p.strip()]

def load_processed_set():
    processed = set()
    if os.path.exists(PROGRESS_CSV):
        with open(PROGRESS_CSV, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for r in reader:
                url = r.get("follower_url") or r.get("follower")
                if url: processed.add(url.strip())
    return processed

def write_progress_row(school, follower_url, abbreviation, result):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    exists = os.path.exists(PROGRESS_CSV)
    with open(PROGRESS_CSV, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(["school","follower_url","abbreviation","result","timestamp"])
        w.writerow([school, follower_url, abbreviation, result, ts])

# ----------------- FOLLOWERS -----------------
def open_followers_modal(driver):
    """
    Opens the followers modal of the current Instagram profile.
    Handles public/private layouts gracefully.
    """
    wait = WebDriverWait(driver, 15)
    try:
        followers_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(@href,'/followers') and .//span]")))
    except:
        try:
            followers_link = wait.until(EC.element_to_be_clickable((By.XPATH, "//ul/li[2]/a[contains(@href,'/followers')]")))
        except:
            try:
                private_text = driver.find_element(By.XPATH, "//*[contains(text(), 'This Account is Private')]")
                if private_text:
                    log("⚠️ Private account — cannot open followers list.")
                    return None
            except:
                pass
            raise

    driver.execute_script("arguments[0].click();", followers_link)
    log("✅ Clicked followers link.")
    modal = None
    try:
        modal = wait.until(EC.presence_of_element_located((By.XPATH, "//div[@role='dialog']//ul")))
        log("✅ Followers modal opened successfully.")
    except Exception as e:
        log(f"⚠️ Timeout waiting for followers modal: {e}")
        return None
    human_sleep(1,1.5)
    return modal

def scroll_followers_modal(driver, modal, target_count):
    followers_elems = []
    last_len = 0
    attempts = 0
    while len(followers_elems) < target_count and attempts < 50:
        items = modal.find_elements(By.XPATH, ".//li//a[contains(@href, '/')]")
        for it in items:
            href = it.get_attribute("href")
            if href and "/p/" not in href and href not in followers_elems:
                followers_elems.append(href)
        driver.execute_script("arguments[0].parentNode.scrollTop = arguments[0].parentNode.scrollHeight", modal)
        human_sleep(SCROLL_DELAY, SCROLL_DELAY+0.5)
        if len(followers_elems) == last_len:
            attempts += 1
        else:
            last_len = len(followers_elems)
    return followers_elems[:target_count]

def get_bio(driver):
    try:
        return driver.find_element(By.XPATH, "//div[@data-testid='user-bio']").text
    except:
        try:
            return driver.find_element(By.XPATH, "//div[@class='-vDIg']/span").text
        except:
            return ""

def click_follow_if_needed(driver):
    try:
        btn = driver.find_element(By.XPATH, "//header//button[contains(., 'Follow')]")
        if "Following" not in btn.text and "Requested" not in btn.text:
            btn.click()
            return True
    except:
        pass
    return False

def process_follower_profile(driver, profile_url, abbreviation_list):
    driver.execute_script("window.open('');")
    driver.switch_to.window(driver.window_handles[-1])
    driver.get(profile_url)
    try:
        WebDriverWait(driver, 8).until(EC.presence_of_element_located((By.TAG_NAME, "header")))
        bio = get_bio(driver).lower()
        found = any(abbr in bio for abbr in abbreviation_list)
        followed = False
        if found:
            followed = click_follow_if_needed(driver)
            human_sleep(1.5,2.5)
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        return found, ("followed" if followed else "no_action")
    except:
        driver.close()
        driver.switch_to.window(driver.window_handles[0])
        return False, "profile_load_fail"

# ----------------- MAIN -----------------
def main():
    log("🚀 Starting Insta Multi Bot")
    try:
        df = pd.read_excel(SCHOOLS_XLSX)
    except Exception as e:
        log(f"❌ Failed to read {SCHOOLS_XLSX}: {e}")
        return

    processed = load_processed_set()
    total_followed = 0

    for _, row in df.iterrows():
        school_name = str(row.get("School Name") or "").strip()
        handles = parse_handles(row.get("Instagram ID"))
        abbr_list = parse_abbreviations(row.get("Abbreviation"))
        max_follow = int(row.get("Max follow per school") or 50)
        bot_user = str(row.get("bot_username") or "").strip()
        bot_pass = str(row.get("bot_password") or "").strip()

        if not bot_user or not bot_pass:
            log(f"⚠️ No bot credentials found for {school_name}, skipping.")
            continue

        driver = start_driver()
        if not login_with_checkpoint_support(driver, bot_user, bot_pass):
            log(f"❌ Login failed for {bot_user}. Skipping {school_name}.")
            continue

        for handle in handles:
            if total_followed >= DAILY_CAP:
                log("🚫 Reached daily follow cap, exiting.")
                break

            log(f"Opening {handle} ...")
            driver.get(f"https://www.instagram.com/{handle}/")
            try:
                WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.TAG_NAME, "header")))
            except:
                log(f"⚠️ Could not open {handle}. Skipping.")
                continue

            modal = open_followers_modal(driver)
            if not modal:
                log(f"⚠️ Skipping {handle} — no followers modal.")
                continue

            target_count = max_follow * FOLLOW_LOAD_FACTOR
            follower_links = scroll_followers_modal(driver, modal, target_count)
            log(f"Loaded {len(follower_links)} followers for {handle}.")

            followed_this_school = 0
            for prof_url in follower_links:
                if prof_url in processed:
                    continue
                if total_followed >= DAILY_CAP or followed_this_school >= max_follow:
                    break
                found, action = process_follower_profile(driver, prof_url, abbr_list)
                write_progress_row(school_name, prof_url, ";".join(abbr_list), f"{found}|{action}")
                processed.add(prof_url)
                if found and action == "followed":
                    total_followed += 1
                    followed_this_school += 1
                    log(f"[+] Followed {prof_url} ({total_followed})")
                elif found:
                    log(f"[i] Match found, already following {prof_url}")
                human_sleep(3,6)

        log(f"✅ Finished {school_name}: {total_followed} total follows so far.")
        safe_logout(driver)
        try: driver.quit()
        except: pass
        human_sleep(6,12)

    log("🏁 All done.")

if __name__ == "__main__":
    main()
