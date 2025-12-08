import streamlit as st
import pandas as pd
import io
import requests
import zipfile

# --- Page Configuration ---
st.set_page_config(page_title="CSV Data QA Tool", layout="wide")

st.title("📊 Bfax Data QA Tool")
st.markdown("""
**Capabilities:**
1. **Source Flexibility:** Upload files or provide a direct download link.
2. **Auto-Detection:** Automatically detects if a file is a ZIP (even if the URL doesn't say .zip).
3. **Smart Column Detection:** Checks for **'Permit Number'** or **'Record Number'** interchangeably.
4. **Global Consistency:** Ensures every ID appears in **all** files.
""")

# --- Helper Functions ---

def normalize_id_column(df):
    """
    Checks for 'Permit Number' or 'Record Number'.
    Returns the column name found, or None if neither exists.
    """
    # normalize columns to lower case for loose matching if needed, 
    # but for now we stick to exact case provided in prompt requirements
    if 'Permit Number' in df.columns:
        return 'Permit Number'
    elif 'Record Number' in df.columns:
        return 'Record Number'
    return None

def read_csv_content(file_buffer):
    """
    Attempts to read CSV from bytes buffer with UTF-8, falling back to Latin-1.
    """
    try:
        return pd.read_csv(file_buffer)
    except UnicodeDecodeError:
        file_buffer.seek(0)
        return pd.read_csv(file_buffer, encoding='latin-1')
    except pd.errors.ParserError:
        # If the file is not a valid CSV
        return None
    except Exception:
        return None

def process_file_data(file_name, file_content_bytes):
    """
    Determines if content is a ZIP or CSV based on content (magic numbers),
    not just the filename.
    Returns a dictionary: {filename: dataframe}
    """
    processed_dfs = {}
    file_buffer = io.BytesIO(file_content_bytes)

    # 1. Try to open as ZIP first (Content-based detection)
    if zipfile.is_zipfile(file_buffer):
        try:
            with zipfile.ZipFile(file_buffer) as z:
                for sub_file in z.namelist():
                    # Ignore MacOS metadata and non-csv files
                    if sub_file.lower().endswith('.csv') and not sub_file.startswith('__MACOSX') and not sub_file.startswith('.'):
                        with z.open(sub_file) as f:
                            df = read_csv_content(f)
                            if df is not None:
                                processed_dfs[sub_file] = df
        except zipfile.BadZipFile:
            st.error(f"Error: The file '{file_name}' appears to be a corrupted zip.")
    
    # 2. If not a ZIP, try to read as a single CSV
    else:
        # Reset buffer position just in case
        file_buffer.seek(0)
        df = read_csv_content(file_buffer)
        if df is not None:
            processed_dfs[file_name] = df
            
    return processed_dfs

# --- Input Section ---
st.sidebar.header("Data Input")
input_method = st.sidebar.radio("Choose Input Method:", ["File Upload", "File URL"])

loaded_dfs = {} # Global store for all dataframes: {filename: dataframe}

if input_method == "File Upload":
    uploaded_files = st.file_uploader("Upload CSV or ZIP files", type=["csv", "zip"], accept_multiple_files=True)
    if uploaded_files:
        for file in uploaded_files:
            # Check file type using the buffer content
            new_dfs = process_file_data(file.name, file.read())
            loaded_dfs.update(new_dfs)

elif input_method == "File URL":
    url = st.text_input("Enter direct file URL:", placeholder="https://dl.objcdn.com/...")
    if url:
        if st.button("Load from URL"):
            with st.spinner("Downloading and processing..."):
                try:
                    response = requests.get(url)
                    response.raise_for_status()
                    
                    # Use URL as temporary filename
                    filename = url.split("/")[-1]
                    if not filename:
                        filename = "downloaded_data"

                    # Process content (auto-detects ZIP vs CSV)
                    new_dfs = process_file_data(filename, response.content)
                    loaded_dfs.update(new_dfs)
                    
                    if not new_dfs:
                        st.error("Could not extract any valid CSV data. Please check if the link points to a CSV or a ZIP containing CSVs.")
                    else:
                        st.success(f"Successfully loaded {len(new_dfs)} file(s) from URL.")
                        
                except Exception as e:
                    st.error(f"Error downloading file: {e}")

# --- Main Processing Logic ---

if loaded_dfs:
    # --- Part 1: Individual File Analysis ---
    st.divider()
    st.header(f"1. Individual File Analysis ({len(loaded_dfs)} files loaded)")
    
    file_names = list(loaded_dfs.keys())
    tabs = st.tabs(file_names)

    # Dictionary to store ID sets for the global cross-check later
    # Format: {filename: set_of_ids}
    file_id_sets = {}

    for i, file_name in enumerate(file_names):
        df = loaded_dfs[file_name]
        with tabs[i]:
            st.subheader(f"📄 {file_name}")
            
            # A. ID Column Check
            id_col = normalize_id_column(df)
            
            if id_col is None:
                st.error("❌ CRITICAL: Neither 'Permit Number' nor 'Record Number' columns were found.")
                file_id_sets[file_name] = set() # Empty set for this file
            else:
                st.info(f"ℹ️ Identified ID Column: **{id_col}**")
                
                # Check for nulls in ID
                id_nulls = df[id_col].isnull().sum()
                if id_nulls == 0:
                    st.success(f"✅ '{id_col}' has no missing values.")
                else:
                    st.error(f"❌ '{id_col}' has {id_nulls} missing values.")
                    st.dataframe(df[df[id_col].isnull()])
                
                # Store IDs for cross-check (convert to string to ensure consistency)
                current_ids = set(df[id_col].dropna().astype(str))
                file_id_sets[file_name] = current_ids

            st.divider()

            # B. Duplicates
            st.markdown("**Duplicate Analysis**")
            default_cols = [id_col] if id_col else []
            
            cols_to_check = st.multiselect(
                f"Check duplicates based on:",
                options=df.columns,
                default=default_cols,
                key=f"dupe_{i}"
            )
            
            if cols_to_check:
                dup_count = df.duplicated(subset=cols_to_check).sum()
                if dup_count == 0:
                    st.success("✅ No duplicates found.")
                else:
                    st.warning(f"⚠️ Found {dup_count} duplicates.")
                    st.dataframe(df[df.duplicated(subset=cols_to_check, keep=False)].sort_values(by=cols_to_check))

    # --- Part 2: Global Cross-File Consistency ---
    st.divider()
    st.header("2. Global Cross-File Consistency")
    st.markdown("Checking that **every** ID appears in **every** file.")

    if len(loaded_dfs) < 2:
        st.warning("⚠️ Need at least 2 files to perform consistency checks.")
    else:
        # 1. Calculate the 'Master Union' (All unique IDs found in ANY file)
        all_ids_union = set().union(*file_id_sets.values())
        
        # 2. Check each file against the Master Union
        inconsistency_found = False
        summary_data = []

        for fname, f_ids in file_id_sets.items():
            missing_ids = all_ids_union - f_ids
            
            if missing_ids:
                inconsistency_found = True
                status = "❌ Inconsistent"
                count_missing = len(missing_ids)
            else:
                status = "✅ Complete"
                count_missing = 0
            
            summary_data.append({
                "File Name": fname,
                "Status": status,
                "Total IDs": len(f_ids),
                "Missing IDs (relative to all files)": count_missing
            })

        st.table(pd.DataFrame(summary_data))

        if not inconsistency_found:
            st.success("🎉 PERFECT MATCH: All files contain exactly the same set of IDs.")
        else:
            st.error("⚠️ Inconsistencies detected. Some files are missing IDs that exist in other files.")
            
            # Detailed Breakdown
            with st.expander("View Detailed Mismatches"):
                for fname, f_ids in file_id_sets.items():
                    missing = all_ids_union - f_ids
                    if missing:
                        st.subheader(f"Missing in: {fname}")
                        st.write(f"This file is missing {len(missing)} IDs that are present in other files:")
                        st.write(list(missing))
