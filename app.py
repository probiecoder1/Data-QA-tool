import streamlit as st
import pandas as pd
import io

# --- Page Configuration ---
st.set_page_config(page_title="CSV Data QA Tool", layout="wide")

st.title("📊 CSV Data QA Tool (Multi-File)")
st.markdown("""
Upload one or more CSV files. The tool will:
1. Check for missing values and duplicates in each file.
2. **Mandatory Check:** Ensure 'Permit Number' exists and is not null in every file.
3. **Cross-Check:** Ensure 'Permit Number' matches between *permit-listings* and *permits-details* files.
""")

# --- Helper Function to Load Data ---
def load_data(file):
    try:
        # Try reading as default UTF-8
        return pd.read_csv(file)
    except UnicodeDecodeError:
        # Fallback to Latin-1 if UTF-8 fails
        file.seek(0)
        return pd.read_csv(file, encoding='latin-1')
    except Exception as e:
        return None

# --- 1. File Upload Section ---
uploaded_files = st.file_uploader("Upload your CSV files", type=["csv"], accept_multiple_files=True)

# Dictionary to store dataframes for cross-file checking later
# Key: Filename, Value: DataFrame
loaded_dfs = {}

if uploaded_files:
    # Create tabs for each file so the page doesn't get too long
    file_names = [f.name for f in uploaded_files]
    tabs = st.tabs(file_names)

    for i, file in enumerate(uploaded_files):
        with tabs[i]:
            st.header(f"File: {file.name}")
            df = load_data(file)
            
            if df is not None:
                # Store for cross-checks
                loaded_dfs[file.name] = df

                # --- A. Mandatory Permit Number Check ---
                st.subheader("1. Mandatory Field Check: 'Permit Number'")
                if 'Permit Number' not in df.columns:
                    st.error("❌ CRITICAL: Column 'Permit Number' is missing from this file!")
                else:
                    permit_nulls = df['Permit Number'].isnull().sum()
                    if permit_nulls == 0:
                        st.success("✅ 'Permit Number' column exists and has no missing values.")
                    else:
                        st.error(f"❌ 'Permit Number' has {permit_nulls} missing values.")
                        # Show the bad rows
                        bad_rows = df[df['Permit Number'].isnull()]
                        st.dataframe(bad_rows)

                st.divider()

                # --- B. Standard Missing Value Analysis ---
                st.subheader("2. General Missing Value Analysis")
                missing_count = df.isnull().sum()
                total_missing = missing_count.sum()
                
                if total_missing == 0:
                    st.info("No missing values found in other columns.")
                else:
                    st.warning(f"Found {total_missing} missing values in total.")
                    st.dataframe(missing_count[missing_count > 0])

                st.divider()

                # --- C. Duplicate Analysis ---
                st.subheader("3. Duplicate Analysis")
                # Default to checking Permit Number if it exists, otherwise check all
                default_cols = ['Permit Number'] if 'Permit Number' in df.columns else []
                
                cols_to_check = st.multiselect(
                    f"Select columns to check for duplicates in {file.name}",
                    options=df.columns,
                    default=default_cols,
                    key=f"dupe_{i}" # Unique key for this widget
                )
                
                subset_arg = cols_to_check if cols_to_check else None
                dup_count = df.duplicated(subset=subset_arg).sum()

                if dup_count == 0:
                    st.success("✅ No duplicates found.")
                else:
                    st.error(f"⚠️ Found {dup_count} duplicates.")
                    dupe_rows = df[df.duplicated(subset=subset_arg, keep=False)].sort_values(by=cols_to_check if cols_to_check else df.columns[0])
                    st.dataframe(dupe_rows)

            else:
                st.error("Failed to load file. Please check encoding.")

    # --- 4. Cross-File Logic (Listings vs Details) ---
    st.divider()
    st.header("4. Cross-File Consistency Check")
    
    # Identify the specific files based on partial name match
    listing_file = next((name for name in loaded_dfs if 'permit-listings' in name.lower()), None)
    details_file = next((name for name in loaded_dfs if 'permits-details' in name.lower()), None)

    if listing_file and details_file:
        st.info(f"Comparing detected files:\n1. Listings: **{listing_file}**\n2. Details: **{details_file}**")
        
        df_list = loaded_dfs[listing_file]
        df_det = loaded_dfs[details_file]

        # Ensure both have the column before comparing
        if 'Permit Number' in df_list.columns and 'Permit Number' in df_det.columns:
            # Convert to sets for comparison (handles different sorting/duplicates)
            set_listings = set(df_list['Permit Number'].dropna().astype(str))
            set_details = set(df_det['Permit Number'].dropna().astype(str))

            # Find mismatches
            in_list_not_details = set_listings - set_details
            in_details_not_list = set_details - set_listings

            if not in_list_not_details and not in_details_not_list:
                st.success("✅ PERFECT MATCH: All Permit Numbers in Listings match Details.")
            else:
                st.error("❌ Mismatch detected between Listings and Details.")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if in_list_not_details:
                        st.warning(f"Found {len(in_list_not_details)} IDs in Listings but MISSING in Details")
                        st.write(list(in_list_not_details))
                    else:
                        st.success("All Listing IDs exist in Details.")

                with col2:
                    if in_details_not_list:
                        st.warning(f"Found {len(in_details_not_list)} IDs in Details but MISSING in Listings")
                        st.write(list(in_details_not_list))
                    else:
                        st.success("All Details IDs exist in Listings.")
        else:
            st.error("Cannot perform cross-check: 'Permit Number' column missing in one of the files.")
    else:
        st.write("Waiting for both 'permit-listings' and 'permits-details' files to be uploaded to run cross-check...")