# streamlit_app.py
import streamlit as st
import pandas as pd
import json
import re
from datetime import datetime
import pytz
import requests
import glob
import os


def fetch_log_files_list(api_url):
    response = requests.get(f"{api_url}/list_log_files")
    if response.status_code == 200:
        return response.json().get('files', [])
    return []

def download_log_file(api_url, filename, save_dir='all_logs'):
    response = requests.get(f"{api_url}/download_log_file/{filename}")
    if response.status_code == 200:
        os.makedirs(save_dir, exist_ok=True)
        with open(os.path.join(save_dir, filename), 'wb') as f:
            f.write(response.content)
        return True
    return False

def load_logs(log_folder_path='all_logs'):
    log_entries = []
    # Get all .log files in the folder
    log_files = glob.glob(os.path.join(log_folder_path, '*.log'))
    for log_file_path in log_files:
        with open(log_file_path, 'r') as log_file:
            buffer = ""
            for line in log_file:
                line = line.rstrip('\n')
                if buffer:
                    buffer += "\n" + line
                else:
                    buffer = line
                if ', extra_info: ' in line:
                    parsed_line = parse_log_line(buffer)
                    if parsed_line:
                        log_entries.append(parsed_line)
                    buffer = ""
            # Handle any remaining buffer
            if buffer:
                parsed_line = parse_log_line(buffer)
                if parsed_line:
                    log_entries.append(parsed_line)
    df = pd.DataFrame(log_entries)
    if not df.empty:
        df['date_time'] = pd.to_datetime(df['date_time'])  # Convert date_time to datetime
    return df

# Define a function to parse a log line
def parse_log_line(line):
    log_pattern = re.compile(
        r"request_id: (?P<request_id>[^,]+), "
        r"(?P<date_time>[^,]+), "
        r"(?P<file_name>[^,]+), "
        r"(?P<function_name>[^,]+), "
        r"(?P<message_type>INFO|ERROR): "
        r"(?P<message>.*), extra_info: (?P<extra_info>.+)",
        re.DOTALL
    )
    match = log_pattern.search(line)
    if match:
        log_data = match.groupdict()
        try:
            log_data['extra_info'] = json.loads(log_data['extra_info'])
        except Exception:
            log_data['extra_info'] = log_data['extra_info']
        return log_data
    return None
# Read the log file and parse each line
def main():
    st.title("Log Viewer")

    # --- New: Sync logs from API ---
    st.header("Sync Log Files from API")
    api_url = st.text_input("API URL (e.g., http://127.0.0.1:8090)", "http://127.0.0.1:8090")
    if st.button("Sync All Logs from API"):
        files = fetch_log_files_list(api_url)
        if files:
            for filename in files:
                success = download_log_file(api_url, filename, save_dir='all_logs')
                if success:
                    st.success(f"Downloaded {filename}")
                else:
                    st.error(f"Failed to download {filename}")
            st.info("All available logs have been synced to the local all_logs directory.")
        else:
            st.warning("No log files found or failed to fetch file list.")

    request_ids = []
    # Load logs into a DataFrame
    df = load_logs()
    if not df.empty and 'date_time' in df.columns:
        df = df.sort_values(by='date_time', ascending=False)
    else:
        st.write("No logs found")
        return  # or handle accordingly    
    # df = df.sort_values(by='date_time', ascending=False)

    # Time zone selection
    time_zones = pytz.all_timezones
    selected_time_zone = st.selectbox("Select Your Time Zone:", options=time_zones, index=time_zones.index('UTC'))

    # Convert log dates from UTC to the selected time zone
    df['date_time'] = df['date_time'].dt.tz_localize('UTC').dt.tz_convert(selected_time_zone)

    # Add a toggle to choose search method
    search_method = st.radio("Search by:", ("Date and Request ID", "Request ID Only"))

    if search_method == "Date and Request ID":
        # Date range picker
        date_range = st.date_input("Select Date Range:", [df['date_time'].min().date(), df['date_time'].max().date()])

        # Ensure both start and end dates are selected
        if len(date_range) == 2:
            start_date, end_date = date_range
            # Convert start and end dates to the selected time zone
            start_date = pd.to_datetime(start_date).tz_localize(selected_time_zone)
            end_date = pd.to_datetime(end_date).tz_localize(selected_time_zone)

            # Filter logs by date range
            df = df[(df['date_time'] >= start_date) & (df['date_time'] <= end_date)]

            # Multi-select for request_ids within the date range
            request_ids = st.multiselect("Select Request IDs:", options=df['request_id'].unique())

            if request_ids:
                df = df[df['request_id'].isin(request_ids)]
        else:
            st.warning("Please select both a start and end date.")   
            return             

    elif search_method == "Request ID Only":
        # Multi-select for request_ids without date filtering
        request_ids = st.multiselect("Select Request IDs:", options=df['request_id'].unique())

        if request_ids:
            df = df[df['request_id'].isin(request_ids)]

    if not df.empty:
        # Sort by date_time
        df = df.sort_values(by=['date_time'])
        
        # Calculate time difference in seconds
        df['time_diff_sec'] = df.groupby('request_id')['date_time'].diff().dt.total_seconds().fillna(0)
        df['time_diff_sec'] = df['time_diff_sec'].round(2)  # <-- Round to 2 decimals

        df = df[['request_id', 'file_name', 'function_name', 'message_type','message', 'date_time', 'time_diff_sec', 'extra_info']]

        # Reset index
        df = df.reset_index(drop=True)
        df['extra_info'] = df['extra_info'].apply(lambda x: json.dumps(x, ensure_ascii=False) if isinstance(x, dict) else str(x))

        # Calculate total time in seconds
        # total_time_sec = df['time_diff_sec'].sum()
        total_time_sec = round(df['time_diff_sec'].sum(), 2)  # <-- Round to 2 decimals

        # st.write(f"Logs for Request IDs: {', '.join(request_ids)}")
        if request_ids:
            st.write(f"Logs for Request IDs: {', '.join(request_ids)}")
        else:
            st.write("Logs for all Request IDs")        
        st.dataframe(df)
        st.write(f"Total Time (sec): {total_time_sec}")

    else:
        st.write("No logs found for the selected criteria.")

if __name__ == "__main__":
    main()