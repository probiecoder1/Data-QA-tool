import streamlit as st
import pandas as pd
import io
import requests
import zipfile

st.set_page_config(page_title="CSV Data QA Tool", layout="wide")

st.title("📊 Universal Data QA Tool")

st.markdown("""
**Capabilities**
- Supports **Bfax** and **non-Bfax** projects
- Upload files or load via **direct URL**
- CSV or ZIP auto-detection
- Global ID consistency checks
- Duplicate detection
- Schema comparison vs previous dataset
- Column-level fill-rate analysis
""")

st.sidebar.header("Project Configuration")

project_type = st.sidebar.radio(
    "Select Project Type",
    ["Bfax", "Other"]
)

if project_type == "Bfax":
    USER_PRIMARY_ID = None
else:
    USER_PRIMARY_ID = st.sidebar.text_input(
        "Enter Primary ID Column Name",
        placeholder="e.g. Application ID"
    ).strip() or None

def normalize_id_column(df, project_type, user_primary_id=None):
    if project_type == "Bfax":
        for col in ["Permit Number", "Record Number"]:
            if col in df.columns:
                return col
        return None
    else:
        if user_primary_id and user_primary_id in df.columns:
            return user_primary_id
        return None


def read_csv_content(file_buffer):
    try:
        return pd.read_csv(file_buffer)
    except UnicodeDecodeError:
        file_buffer.seek(0)
        return pd.read_csv(file_buffer, encoding="latin-1")
    except Exception:
        return None


def process_file_data(file_name, file_content_bytes):
    processed = {}
    buffer = io.BytesIO(file_content_bytes)

    if zipfile.is_zipfile(buffer):
        with zipfile.ZipFile(buffer) as z:
            for f in z.namelist():
                if f.lower().endswith(".csv") and not f.startswith((".", "__MACOSX")):
                    with z.open(f) as sub:
                        df = read_csv_content(sub)
                        if df is not None:
                            processed[f] = df
    else:
        buffer.seek(0)
        df = read_csv_content(buffer)
        if df is not None:
            processed[file_name] = df

    return processed


def column_profile(df):
    total = len(df)
    return {
        col: round((df[col].notna().sum() / total) * 100, 2) if total else 0
        for col in df.columns
    }

# ----------------------------------------------------
# Current Data Input
# ----------------------------------------------------
st.sidebar.header("Current Dataset")

input_method = st.sidebar.radio(
    "Load Current Data Via",
    ["File Upload", "File URL"]
)

loaded_dfs = {}

if input_method == "File Upload":
    files = st.sidebar.file_uploader(
        "Upload CSV or ZIP",
        type=["csv", "zip"],
        accept_multiple_files=True
    )
    if files:
        for f in files:
            loaded_dfs.update(process_file_data(f.name, f.read()))

else:
    url = st.sidebar.text_input("Enter Direct File URL")
    if url and st.sidebar.button("Load Current Data"):
        r = requests.get(url)
        r.raise_for_status()
        name = url.split("/")[-1] or "current_data"
        loaded_dfs.update(process_file_data(name, r.content))

# ----------------------------------------------------
# Previous Data Input
# ----------------------------------------------------
st.sidebar.header("Previous Dataset (Optional)")

prev_method = st.sidebar.radio(
    "Load Previous Data Via",
    ["None", "File Upload", "File URL"]
)

previous_dfs = {}

if prev_method == "File Upload":
    prev_files = st.sidebar.file_uploader(
        "Upload Previous CSV or ZIP",
        type=["csv", "zip"],
        accept_multiple_files=True,
        key="prev"
    )
    if prev_files:
        for f in prev_files:
            previous_dfs.update(process_file_data(f.name, f.read()))

elif prev_method == "File URL":
    prev_url = st.sidebar.text_input("Previous Dataset URL")
    if prev_url and st.sidebar.button("Load Previous Data"):
        r = requests.get(prev_url)
        r.raise_for_status()
        name = prev_url.split("/")[-1] or "previous_data"
        previous_dfs.update(process_file_data(name, r.content))

if loaded_dfs:
    st.divider()
    st.header("1️⃣ Individual File QA")

    file_id_sets = {}
    tabs = st.tabs(list(loaded_dfs.keys()))

    for i, fname in enumerate(loaded_dfs):
        df = loaded_dfs[fname]

        with tabs[i]:
            st.subheader(fname)

            id_col = normalize_id_column(df, project_type, USER_PRIMARY_ID)

            if not id_col:
                st.error("❌ Primary ID column not found")
                file_id_sets[fname] = set()
            else:
                st.success(f"Primary ID: {id_col}")

                nulls = df[id_col].isnull().sum()
                if nulls:
                    st.error(f"{nulls} missing ID values")
                    st.dataframe(
                        df[df[id_col].isnull()]
                        .head(5)
                        .rename_axis("Row")
                        .reset_index()
                    )
                else:
                    st.success("No missing IDs")

                file_id_sets[fname] = set(df[id_col].dropna().astype(str))

            st.markdown("**Duplicate Check**")
            dup_cols = st.multiselect(
                "Check duplicates on",
                options=df.columns,
                default=[id_col] if id_col else [],
                key=f"dup_{i}"
            )

            if dup_cols:
                dupes = df[df.duplicated(dup_cols, keep=False)]
                if dupes.empty:
                    st.success("No duplicates found")
                else:
                    st.warning(f"{len(dupes)} duplicate rows")
                    st.dataframe(dupes.head(10))

    # ------------------------------------------------
    # Cross-File ID Consistency
    # ------------------------------------------------
    st.divider()
    st.header("2️⃣ Cross-File ID Consistency")

    if len(file_id_sets) > 1:
        union_ids = set().union(*file_id_sets.values())

        summary = []
        inconsistent = False

        for fname, ids in file_id_sets.items():
            missing = union_ids - ids
            if missing:
                inconsistent = True
                status = "❌ Inconsistent"
            else:
                status = "✅ Complete"

            summary.append({
                "File": fname,
                "Status": status,
                "Unique IDs": len(ids),
                "Missing IDs": len(missing)
            })

        st.table(pd.DataFrame(summary))

        if not inconsistent:
            st.success("All files contain identical ID sets")

    # ------------------------------------------------
    # Previous Dataset Comparison
    # ------------------------------------------------
    if previous_dfs:
        st.divider()
        st.header("3️⃣ Previous Dataset Comparison")

        for fname, curr_df in loaded_dfs.items():
            if fname not in previous_dfs:
                st.warning(f"No previous file found for {fname}")
                continue

            prev_df = previous_dfs[fname]

            curr_cols = set(curr_df.columns)
            prev_cols = set(prev_df.columns)

            missing_cols = prev_cols - curr_cols
            new_cols = curr_cols - prev_cols
            common_cols = curr_cols & prev_cols

            st.subheader(fname)

            if not missing_cols and not new_cols:
                st.success("No schema changes")
            else:
                if missing_cols:
                    st.error(f"Missing Columns: {', '.join(sorted(missing_cols))}")
                if new_cols:
                    st.warning(f"New Columns: {', '.join(sorted(new_cols))}")

            curr_fill = column_profile(curr_df)
            prev_fill = column_profile(prev_df)

            rows = []
            for col in common_cols:
                rows.append({
                    "Column": col,
                    "Previous Fill %": prev_fill[col],
                    "Current Fill %": curr_fill[col],
                    "Δ Change": round(curr_fill[col] - prev_fill[col], 2)
                })

            if rows:
                st.markdown("**Fill Rate Comparison (%)**")
                st.dataframe(
                    pd.DataFrame(rows)
                    .sort_values("Δ Change")
                    .reset_index(drop=True)
                )
