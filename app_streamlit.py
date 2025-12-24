import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time
import json
from pathlib import Path

from retap_core import TxSimulator, OnlineAnomalyModel, Featureizer

#############################################
# PAGE CONFIGURATION
#############################################

st.set_page_config(
    page_title="TransGuard - Real-Time Bank Transaction Anomaly Platform",
    page_icon="nippotica_icon.png",
    layout="wide",
    initial_sidebar_state="expanded"
)

#############################################
# SESSION STATE INITIALIZATION
#############################################

def init_session_state():
    """Initialize session state variables"""
    if 'initialized' not in st.session_state:
        # Load config
        cfg_path = Path("sample_config.json")
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
        else:
            cfg = {
                "seed": 42,
                "tx_per_second": 10,
                "num_senders": 50,
                "num_receivers": 50,
                "burst_prob": 0.05,
                "anomaly_prob": 0.02
            }
        
        st.session_state.cfg = cfg
        st.session_state.sim = TxSimulator(**cfg)
        st.session_state.feat = Featureizer()
        st.session_state.model = OnlineAnomalyModel()
        st.session_state.df = pd.DataFrame(columns=["ts", "sender", "receiver", "amount", "hour", "score"])
        st.session_state.is_running = False
        st.session_state.window_seconds = 60
        st.session_state.threshold = 0.75
        st.session_state.initialized = True

init_session_state()

#############################################
# CORE PROCESSING FUNCTIONS
#############################################

def score_batch(df_in: pd.DataFrame) -> pd.DataFrame:
    """Score a batch of transactions"""
    rows = []
    for row in df_in.itertuples(index=False):
        x, meta = st.session_state.feat.transform_row(row)
        s = st.session_state.model.score(x)
        rows.append({**meta, **x, "score": float(s)})
    
    out = pd.DataFrame(rows)
    if not out.empty:
        out["ts"] = pd.to_datetime(out["ts"], utc=True, errors="coerce")
        out["score"] = pd.to_numeric(out["score"], errors="coerce")
        out = out.dropna(subset=["ts", "score"])
    return out


def append_and_window(df_new: pd.DataFrame, window_seconds: int):
    """Append new data and apply time window"""
    if df_new.empty:
        return
    
    all_df = pd.concat([st.session_state.df, df_new], ignore_index=True)
    horizon = pd.Timestamp.now(tz="UTC") - pd.Timedelta(seconds=window_seconds)
    st.session_state.df = all_df[all_df["ts"] >= horizon].reset_index(drop=True)


def generate_step(window_seconds: int):
    """Generate one batch of transactions"""
    batch = st.session_state.sim.generate_batch(n=st.session_state.cfg.get("tx_per_second", 10))
    scored = score_batch(batch)
    append_and_window(scored, window_seconds)


#############################################
# VISUALIZATION FUNCTIONS
#############################################

def create_time_series_plot(df: pd.DataFrame, threshold: float):
    """Create stem plot (lollipop chart) matching Energex style"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data yet. Click 'Step Once' or toggle 'Run Stream'",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#666666")
        )
        fig.update_layout(
            height=350,
            template="plotly_white",
            margin=dict(l=40, r=20, t=30, b=40)
        )
        return fig
    
    # Sort by time
    df = df.sort_values("ts").tail(2000).copy()
    
    # Remove duplicate timestamps - keep last occurrence
    df = df.drop_duplicates(subset=['ts'], keep='last')
    
    # Mark alerts
    df["alert"] = df["score"] >= threshold
    
    # Create figure
    fig = go.Figure()
    
    # Create stems efficiently using single trace with None separators
    df_normal = df[~df["alert"]]
    if not df_normal.empty:
        # Build stems as one trace with None separators
        x_stems = []
        y_stems = []
        for _, row in df_normal.iterrows():
            x_stems.extend([row["ts"], row["ts"], None])
            y_stems.extend([0, row["score"], None])
        
        # All stems in one trace
        fig.add_trace(go.Scatter(
            x=x_stems,
            y=y_stems,
            mode='lines',
            line=dict(color='#9b59b6', width=1.5),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # All dots in one trace
        fig.add_trace(go.Scatter(
            x=df_normal["ts"],
            y=df_normal["score"],
            mode='markers',
            marker=dict(size=4, color='#9b59b6'),
            name='Normal',
            hovertemplate='<b>%{x}</b><br>Score: %{y:.3f}<extra></extra>'
        ))
    
    # Alert scores - red stems with diamond dots
    df_alert = df[df["alert"]]
    if not df_alert.empty:
        # Build stems as one trace with None separators
        x_stems = []
        y_stems = []
        for _, row in df_alert.iterrows():
            x_stems.extend([row["ts"], row["ts"], None])
            y_stems.extend([0, row["score"], None])
        
        # All stems in one trace
        fig.add_trace(go.Scatter(
            x=x_stems,
            y=y_stems,
            mode='lines',
            line=dict(color='#d62728', width=2),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # All dots in one trace
        fig.add_trace(go.Scatter(
            x=df_alert["ts"],
            y=df_alert["score"],
            mode='markers',
            marker=dict(size=6, color='#d62728', symbol='diamond'),
            name='Alert',
            hovertemplate='<b>🚨 ALERT</b><br>%{x}<br>Score: %{y:.3f}<extra></extra>'
        ))
    
    # Threshold line
    fig.add_hline(
        y=threshold,
        line_dash="dash",
        line_color="#d62728",
        line_width=1.5,
        annotation_text=f"Threshold ({threshold:.2f})",
        annotation_position="right"
    )
    
    # Layout matching Energex style
    fig.update_layout(
        height=350,
        template="plotly_white",
        showlegend=True,
        hovermode='closest',
        xaxis_title="Time (UTC)",
        yaxis_title="Anomaly Score",
        margin=dict(l=40, r=20, t=30, b=60),
        font=dict(family="Arial, sans-serif", size=11),
        xaxis=dict(
            showgrid=True, 
            gridwidth=1, 
            gridcolor='lightgray',
            tickangle=-45,
            tickformat='%H:%M:%S'
        ),
        yaxis=dict(range=[0, 1], showgrid=True, gridwidth=1, gridcolor='lightgray'),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            bgcolor='rgba(255, 255, 255, 0.8)',
            bordercolor='lightgray',
            borderwidth=1
        )
    )
    
    return fig


def create_distribution_plot(df: pd.DataFrame, threshold: float):
    """Create histogram of score distribution"""
    if df.empty:
        fig = go.Figure()
        fig.update_layout(height=150, template="plotly_white", margin=dict(l=40, r=20, t=20, b=40))
        return fig
    
    df["alert"] = df["score"] >= threshold
    
    # Create histogram
    fig = go.Figure()
    
    # Normal scores
    fig.add_trace(go.Histogram(
        x=df[~df["alert"]]["score"],
        nbinsx=30,
        name="Normal",
        marker_color="#1f77b4",
        opacity=0.7
    ))
    
    # Alert scores
    if df["alert"].any():
        fig.add_trace(go.Histogram(
            x=df[df["alert"]]["score"],
            nbinsx=30,
            name="Alert",
            marker_color="#d62728",
            opacity=0.7
        ))
    
    fig.update_layout(
        height=150,
        template="plotly_white",
        xaxis_title="Score",
        yaxis_title="Count",
        barmode='stack',
        margin=dict(l=40, r=20, t=20, b=40),
        showlegend=False,
        font=dict(family="IBM Plex Sans, ui-sans-serif, system-ui, sans-serif")
    )
    
    return fig


def get_metrics(df: pd.DataFrame, threshold: float):
    """Calculate current metrics"""
    total_tx = len(df)
    alerts = int((df["score"] >= threshold).sum()) if not df.empty else 0
    mean_score = round(float(df["score"].mean()), 3) if not df.empty else 0.0
    
    # Status
    if mean_score < 0.3:
        status = "✅ Normal"
    elif mean_score < 0.7:
        status = "⚠️ Elevated"
    else:
        status = "🚨 High Risk"
    
    return total_tx, alerts, mean_score, status


#############################################
# MAIN APP LAYOUT
#############################################

# Header
st.markdown("""
# TransGuard: Real-Time Bank Transaction Anomaly Platform
**Nippotica Corporation** | Nippofin Business Unit | AI-Powered Surveillance
""")

# Sidebar - Controls
with st.sidebar:
    st.markdown("### Controls")
    
    # Run/Stop buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("▶️ Start Stream", use_container_width=True, type="primary"):
            st.session_state.is_running = True
            st.rerun()
    with col2:
        if st.button("⏸️ Stop Stream", use_container_width=True):
            st.session_state.is_running = False
            st.rerun()
    
    # Step and Clear buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("⏭️ Step Once", use_container_width=True):
            generate_step(st.session_state.window_seconds)
            st.rerun()
    with col2:
        if st.button("🗑️ Clear Data", use_container_width=True, type="secondary"):
            st.session_state.df = pd.DataFrame(columns=["ts", "sender", "receiver", "amount", "hour", "score"])
            st.session_state.feat = Featureizer()
            st.session_state.model = OnlineAnomalyModel()
            st.session_state.sim = TxSimulator(**st.session_state.cfg)
            st.rerun()
    
    # Stream status
    if st.session_state.is_running:
        st.success("🟢 Stream is RUNNING")
    else:
        st.info("⚪ Stream is STOPPED")
    
    st.markdown("---")
    st.markdown("### Settings")
    
    window_seconds = st.slider(
        "Time Window (seconds)",
        min_value=10,
        max_value=300,
        value=st.session_state.window_seconds,
        step=10,
        help="How much history to keep"
    )
    st.session_state.window_seconds = window_seconds
    
    threshold = st.slider(
        "Alert Threshold",
        min_value=0.0,
        max_value=1.0,
        value=st.session_state.threshold,
        step=0.01,
        help="Score above this triggers alert"
    )
    st.session_state.threshold = threshold
    
    st.markdown("---")
    st.markdown("### Configuration")
    st.json(st.session_state.cfg)
    
    st.markdown("---")
    st.markdown("""
    ### About TransGuard
    
    Real-time anomaly detection using:
    - **Online Learning**: Isolation Forest
    - **Welford's Algorithm**: Efficient streaming statistics
    - **Z-Score Features**: Per-sender normalization
    
    **Contact:** nippofin@nippotica.jp
    """)

# Main dashboard area
df = st.session_state.df.copy()
total_tx, alerts, mean_score, status = get_metrics(df, st.session_state.threshold)

# Metrics row
st.markdown("### Dashboard")
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Transactions in Window", total_tx)
with col2:
    st.metric("🚨 Alerts", alerts)
with col3:
    st.metric("Mean Score", f"{mean_score:.3f}")
with col4:
    st.metric("Status", status)

# Time series plot
st.markdown("### Anomaly Score Timeline")
time_plot = create_time_series_plot(df, st.session_state.threshold)
st.plotly_chart(time_plot, use_container_width=True)

# Distribution plot
st.markdown("### Score Distribution")
dist_plot = create_distribution_plot(df, st.session_state.threshold)
st.plotly_chart(dist_plot, use_container_width=True)

# Transaction table - Only Alerts
st.markdown("### 🚨 Alert Transactions")
alert_df = df[df["score"] >= st.session_state.threshold][["ts", "sender", "receiver", "amount", "score"]].copy()
if not alert_df.empty:
    # Sort by score descending
    alert_df = alert_df.sort_values("score", ascending=False)
    alert_df["ts"] = alert_df["ts"].dt.strftime("%H:%M:%S")
    alert_df["score"] = alert_df["score"].round(3)
    st.dataframe(alert_df, use_container_width=True, hide_index=True)
    st.caption(f"Showing {len(alert_df)} alert transaction(s) with score ≥ {st.session_state.threshold:.2f}")
elif not df.empty:
    st.success("✅ No alerts in current window. All transactions are normal.")
else:
    st.info("No transactions yet. Click 'Step Once' or 'Start Stream' to generate data.")

# Footer
st.markdown("""
---
**TransGuard v1.0** | Nippotica Corporation | Nippofin Business Unit | Powered by Isolation Forest ML
""")

#############################################
# AUTO-REFRESH LOGIC
#############################################

# If stream is running, generate a step and rerun
if st.session_state.is_running:
    generate_step(st.session_state.window_seconds)
    time.sleep(1)  # Wait 1 second between updates
    st.rerun()
