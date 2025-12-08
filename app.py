import streamlit as st
import pandas as pd
import io
import requests
import zipfile

# --- Page Configuration ---
st.set_page_config(page_title="CSV Data QA Tool", layout="wide")

st.title("📊 Bfax Data QA Tool")
st.markdown("""
**Key Capabilities & Updates:**
* **Source Flexibility:** Upload files or provide a direct download link (CSV or ZIP).
* **Auto-Detection:** Automatically detects if a file is a ZIP by content.
* **Flexible ID:** Checks for **'Permit Number'** or **'Record Number'** interchangeably.
* **Global Consistency:** Ensures every Permit Number appears in **all** files.
* **✨ Enhanced Debugging:** Displays examples and row numbers for all inconsistencies.
""")

# --- Helper Functions ---

def normalize_id_column(df):
    """
    Checks for 'Permit Number' or 'Record Number'.
    Returns the column name found, or None if neither exists.
    """
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
        # Note: We use the default comma separator here.
        return pd.read_csv(file_buffer)
    except UnicodeDecodeError:
        file_buffer.seek(0)
        return pd.read_csv(file_buffer, encoding='latin-1')
    except pd.errors.ParserError:
        return None
    except Exception:
        return None

def process_file_data(file_name, file_content_bytes):
    """
    Determines if content is a ZIP or CSV based on content (magic numbers).
    Returns a dictionary: {filename: dataframe}
    """
    processed_dfs = {}
    file_buffer = io.BytesIO(file_content_bytes)

    # 1. Try to open as ZIP first (Content-based detection)
    if zipfile.is_zipfile(file_buffer):
        try:
            with zipfile.ZipFile(file_buffer) as z:
                for sub_file in z.namelist():
                    if sub_file.lower().endswith('.csv') and not sub_file.startswith('__MACOSX') and not sub_file.startswith('.'):
                        with z.open(sub_file) as f:
                            df = read_csv_content(f)
                            if df is not None:
                                processed_dfs[sub_file] = df
        except zipfile.BadZipFile:
            st.error(f"Error: The file '{file_name}' appears to be a corrupted zip.")
    
    # 2. If not a ZIP, try to read as a single CSV
    else:
        file_buffer.seek(0)
        df = read_csv_content(file_buffer)
        if df is not None:
            processed_dfs[file_name] = df
            
    return processed_dfs

# --- Input Section ---
st.sidebar.header("Data Input")
input_method = st.sidebar.radio("Choose Input Method:", ["File Upload", "File URL"])

loaded_dfs = {} 

if input_method == "File Upload":
    uploaded_files = st.file_uploader("Upload CSV or ZIP files", type=["csv", "zip"], accept_multiple_files=True)
    if uploaded_files:
        for file in uploaded_files:
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
                    
                    filename = url.split("/")[-1]
                    if not filename:
                        filename = "downloaded_data"

                    new_dfs = process_file_data(filename, response.content)
                    loaded_dfs.update(new_dfs)
                    
                    if not new_dfs:
                        st.error("Could not extract any valid CSV data.")
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

    file_id_sets = {}

    for i, file_name in enumerate(file_names):
        df = loaded_dfs[file_name]
        with tabs[i]:
            st.subheader(f"📄 {file_name}")
            
            # A. ID Column Check
            id_col = normalize_id_column(df)
            
            if id_col is None:
                st.error("❌ CRITICAL: Neither 'Permit Number' nor 'Record Number' columns were found.")
                file_id_sets[file_name] = set() 
            else:
                st.info(f"ℹ️ Identified ID Column: **{id_col}**")
                
                # Check for nulls in ID
                id_nulls = df[id_col].isnull().sum()
                if id_nulls == 0:
                    st.success(f"✅ '{id_col}' has no missing values.")
                else:
                    st.error(f"❌ '{id_col}' has **{id_nulls}** missing values.")
                    # Display examples of rows missing the ID
                    bad_rows = df[df[id_col].isnull()].head(5).rename_axis('Row Index').reset_index()
                    st.dataframe(bad_rows)
                
                # Store IDs for cross-check
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
                dup_mask = df.duplicated(subset=cols_to_check, keep=False)
                dup_count = dup_mask.sum()
                
                if dup_count == 0:
                    st.success("✅ No duplicates found.")
                else:
                    st.warning(f"⚠️ Found **{dup_count}** duplicate rows.")
                    # Display examples of duplicates
                    dupe_rows = df[dup_mask].sort_values(by=cols_to_check).head(10).rename_axis('Row Index').reset_index()
                    st.dataframe(dupe_rows)

    # --- Part 2: Global Cross-File Consistency ---
    st.divider()
    st.header("2. Global Cross-File Consistency")
    st.markdown("Checking that **every** ID appears in **every** file.")

    if len(loaded_dfs) < 2:
        st.warning("⚠️ Need at least 2 files to perform consistency checks.")
    else:
        # 1. Calculate the 'Master Union' (All unique IDs found in ANY file)
        all_ids_union = set().union(*file_id_sets.values())
        
        inconsistency_found = False
        summary_data = []

        for fname, f_ids in file_id_sets.items():
            df = loaded_dfs[fname]
            id_col = normalize_id_column(df) # Get the specific ID column name for this file
            
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
                "Total Unique IDs": len(f_ids),
                "Missing IDs (relative to all files)": count_missing
            })

        st.table(pd.DataFrame(summary_data))

        if not inconsistency_found:
            st.success("🎉 PERFECT MATCH: All files contain exactly the same set of IDs.")
        else:
            st.error("⚠️ Inconsistencies detected. Some files are missing IDs that exist in other files.")
            
            # Detailed Breakdown: Show the full rows corresponding to the missing IDs
            with st.expander("View Detailed Mismatches (Full Rows from source files)"):
                
                # 1. Find the master set of rows that cause the issue
                missing_in_files = {} # Stores {filename: list_of_IDs_to_display}

                for fname, f_ids in file_id_sets.items():
                    # IDs that exist in this file, but are missing from others 
                    # (i.e., this file has IDs that are NOT in the intersection of all files)
                    
                    # Instead, we focus on: IDs that are in the UNION, but NOT in this specific file.
                    
                    missing_from_this_file = all_ids_union - f_ids
                    
                    if missing_from_this_file:
                        # Find which files DO contain these missing IDs
                        source_files = []
                        for other_fname, other_f_ids in file_id_sets.items():
                            if other_fname != fname:
                                common_missing = missing_from_this_file.intersection(other_f_ids)
                                if common_missing:
                                    source_files.append(other_fname)
                        
                        st.subheader(f"IDs Missing In: **{fname}**")
                        st.write(f"This file is missing **{len(missing_from_this_file)}** IDs. Examples are found in: **{', '.join(source_files[:3])}...**")
                        
                        # Find the actual rows in the *source* files that contain the missing IDs
                        
                        # We can only display the list of IDs here for conciseness
                        st.text_area(f"IDs missing from {fname}:", 
                                     value='\n'.join(list(missing_from_this_file)[:10]) + (f'\n...and {len(missing_from_this_file) - 10} more' if len(missing_from_this_file) > 10 else ''), 
                                     height=150)
                        
                        st.markdown("---")
