import os
import re
import urllib.parse
from datetime import datetime
import psycopg2

# --- DATABASE CONNECTION ---
def get_db_connection():
    # GitHub Actions will inject this safely from our Secrets
    db_url = os.environ.get("DATABASE_URL")
    
    cert_path = "root.crt"
    safe_cert_path = urllib.parse.quote(cert_path)
    
    if "&sslrootcert" in db_url:
        db_url = db_url.split("&sslrootcert")[0]
    
    db_url = f"{db_url}&sslrootcert={safe_cert_path}"
    return psycopg2.connect(db_url)

# --- DYNAMIC END TIME EXTRACTOR ---
def parse_shift_end_time(shift_string):
    """ Scans the shift name and grabs the END time (e.g., the '8:30 PM' from '12:00 PM to 8:30 PM') """
    match = re.search(r"(?:to|-)\s*(\d{1,2}):(\d{2})\s*(AM|PM)", shift_string, re.IGNORECASE)
    if match:
        h = int(match.group(1))
        m = int(match.group(2))
        meridian = match.group(3).upper()
        
        if meridian == "PM" and h != 12: h += 12
        elif meridian == "AM" and h == 12: h = 0
        
        return f"{h:02d}:{m:02d}:00"
    return "18:00:00" # Fallback to 6:00 PM if it can't read the text

# --- THE SWEEPER FUNCTION ---
def run_midnight_sweep():
    print("Starting Auto-Clockout Sweep...")
    today = datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Find everyone who clocked in today but has NO clock out time
    query = """
        SELECT a.id, e.department, a.notes 
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        WHERE a.date = %s AND a.clock_out_time IS NULL
    """
    cursor.execute(query, (today,))
    open_shifts = cursor.fetchall()
    
    if not open_shifts:
        print("All good! No missing clock-outs found today.")
        conn.close()
        return

    # Process each missing clock-out
    count = 0
    for record_id, department, existing_notes in open_shifts:
        scheduled_end_time = parse_shift_end_time(department)
        
        # Append a flag so you know the system did this, not the user
        new_notes = f"{existing_notes} [Auto-Closed]" if existing_notes else "[Auto-Closed]"
        
        cursor.execute(
            "UPDATE attendance SET clock_out_time = %s, notes = %s WHERE id = %s", 
            (scheduled_end_time, new_notes, record_id)
        )
        count += 1

    conn.commit()
    conn.close()
    print(f"Sweep Complete! Auto-resolved {count} missing clock-outs for {today}.")

if __name__ == "__main__":
    run_midnight_sweep()