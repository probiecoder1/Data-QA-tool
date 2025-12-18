import streamlit as st
import pandas as pd
import io
import requests
import zipfile
from typing import Dict, Optional, Set

st.set_page_config(
    page_title="Data QA Engine",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    .stMetric { background-color: #ffffff; padding: 15px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    .qa-card { padding: 20px; border: 1px solid #e6e9ef; border-radius: 10px; background: white; margin-bottom: 20px; }
    div[data-testid="stExpander"] { border: none !important; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    </style>
""", unsafe_allow_html=True)

class DataProcessor:
    @staticmethod
    @st.cache_data(show_spinner=False)
    def load_csv(buffer: io.BytesIO) -> Optional[pd.DataFrame]:
        try:
            buffer.seek(0)
            return pd.read_csv(buffer)
        except UnicodeDecodeError:
            buffer.seek(0)
            return pd.read_csv(buffer, encoding="latin-1")
        except Exception as e:
            st.error(f"Processing Error: {str(e)}")
            return None

    @classmethod
    def process_input(cls, name: str, content: bytes) -> Dict[str, pd.DataFrame]:
        results = {}
        buffer = io.BytesIO(content)
        if zipfile.is_zipfile(buffer):
            with zipfile.ZipFile(buffer) as z:
                for f in z.namelist():
                    if f.lower().endswith(".csv") and not f.startswith((".", "__MACOSX")):
                        with z.open(f) as sub:
                            df = cls.load_csv(io.BytesIO(sub.read()))
                            if df is not None: results[f] = df
        else:
            df = cls.load_csv(buffer)
            if df is not None: results[name] = df
        return results

class QAEngine:
    def __init__(self, project_type: str, user_id: Optional[str]):
        self.project_type = project_type
        self.user_id = user_id

    def get_id_col(self, df: pd.DataFrame) -> Optional[str]:
        if self.project_type == "Bfax":
            for col in ["Permit Number", "Record Number"]:
                if col in df.columns: return col
        elif self.user_id in df.columns:
            return self.user_id
        return None

    def get_fill_rate(self, df: pd.DataFrame) -> Dict[str, float]:
        if len(df) == 0: return {c: 0.0 for c in df.columns}
        return {c: round((df[c].notna().sum() / len(df)) * 100, 2) for c in df.columns}

def main():
    with st.sidebar:
        st.title("🛡️ QA Engine Config")
        ptype = st.radio("Project Context", ["Bfax", "Standard"])
        uid = st.text_input("Target ID Column", placeholder="e.g. GUID") if ptype == "Standard" else None
        
        st.divider()
        
        src_mode = st.radio("Source Mode", ["Upload", "Remote URL"])
        curr_data = {}
        if src_mode == "Upload":
            files = st.file_uploader("Current Files", type=["csv", "zip"], accept_multiple_files=True)
            if files:
                for f in files: curr_data.update(DataProcessor.process_input(f.name, f.read()))
        else:
            url = st.text_input("Data URL")
            if url and st.button("Fetch Data"):
                r = requests.get(url)
                curr_data.update(DataProcessor.process_input(url.split("/")[-1], r.content))

        prev_files = st.file_uploader("Previous Dataset (Comparison)", type=["csv", "zip"], accept_multiple_files=True)
        prev_data = {}
        if prev_files:
            for f in prev_files: prev_data.update(DataProcessor.process_input(f.name, f.read()))

    engine = QAEngine(ptype, uid)

    if not curr_data:
        st.info("👋 Welcome! Please load a dataset from the sidebar to begin auditing.")
        return

    st.header("📋 Audit Dashboard")
    
    file_ids: Dict[str, Set[str]] = {}
    
    tabs = st.tabs([f"📄 {name}" for name in curr_data.keys()])
    for i, (name, df) in enumerate(curr_data.items()):
        with tabs[i]:
            id_col = engine.get_id_col(df)
            
            m1, m2, m3 = st.columns(3)
            m1.metric("Total Rows", f"{len(df):,}")
            m2.metric("Total Columns", len(df.columns))
            
            if id_col:
                ids = set(df[id_col].dropna().astype(str))
                file_ids[name] = ids
                m3.metric("Unique IDs", f"{len(ids):,}")
                
                if df[id_col].isnull().any():
                    st.warning(f"Found {df[id_col].isnull().sum()} null values in ID column.")
            else:
                m3.status("ID Missing", state="error")

            col_left, col_right = st.columns([1, 1])
            with col_left:
                st.subheader("Data Preview")
                st.dataframe(df.head(10), use_container_width=True)
            
            with col_right:
                st.subheader("Uniqueness Audit")
                checks = st.multiselect("Columns to verify", df.columns, default=[id_col] if id_col else [], key=f"check_{name}")
                if checks:
                    dupes = df[df.duplicated(checks, keep=False)]
                    if not dupes.empty:
                        st.error(f"Violation: {len(dupes)} non-unique rows detected.")
                        st.dataframe(dupes.head(5))
                    else:
                        st.success("Uniqueness constraints validated.")

    if len(file_ids) > 1:
        st.divider()
        st.header("🔗 Integrity Check (Cross-File)")
        all_ids = set().union(*file_ids.values())
        sync_report = []
        for fname, ids in file_ids.items():
            diff = all_ids - ids
            sync_report.append({"Filename": fname, "Coverage": f"{(len(ids)/len(all_ids))*100:.1f}%", "Missing": len(diff)})
        st.table(pd.DataFrame(sync_report))

    if prev_data:
        st.divider()
        st.header("📉 Regression Analysis")
        for name, df in curr_data.items():
            if name in prev_data:
                with st.expander(f"Delta Analysis: {name}"):
                    pdf = prev_data[name]
                    curr_f, prev_f = engine.get_fill_rate(df), engine.get_fill_rate(pdf)
                    
                    diffs = []
                    for c in set(df.columns) & set(pdf.columns):
                        delta = curr_f[c] - prev_f[c]
                        diffs.append({"Column": c, "Current %": curr_f[c], "Prev %": prev_f[c], "Change": delta})
                    
                    res_df = pd.DataFrame(diffs).sort_values("Change")
                    st.dataframe(res_df.style.background_gradient(subset=['Change'], cmap='RdYlGn'), use_container_width=True)

if __name__ == "__main__":
    main()
