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

def create_scatter_plot(df: pd.DataFrame, threshold: float):
    """Create dot-size scatter plot with random jitter for visual separation - v3.0"""
    if df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="No data yet. Click 'Step Once' or 'Start Stream'",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=14, color="#666666")
        )
        fig.update_layout(
            height=450,
            template="plotly_white",
            margin=dict(l=60, r=20, t=30, b=60)
        )
        return fig
    
    # Force a fresh dataframe copy to avoid caching issues
    df = df.copy()
    
    # Calculate score distribution
    # Bin scores into discrete levels for cleaner visualization
    num_bins = 50  # More bins for finer granularity
    score_bins = np.linspace(0, 1, num_bins + 1)
    df['score_bin'] = pd.cut(df['score'], bins=score_bins, labels=False, include_lowest=True)
    
    # Calculate percentage for each bin
    total_count = len(df)
    bin_counts = df.groupby('score_bin').size()
    bin_percentages = (bin_counts / total_count * 100).to_dict()
    
    # Calculate actual score values for each bin (midpoint)
    bin_scores = {}
    for bin_idx in bin_counts.index:
        bin_scores[bin_idx] = (score_bins[bin_idx] + score_bins[bin_idx + 1]) / 2
    
    # Determine if each bin is alert or normal
    bin_is_alert = {bin_idx: bin_scores[bin_idx] >= threshold for bin_idx in bin_counts.index}
    
    # Prepare data for plotting
    normal_bins = [(bin_idx, bin_scores[bin_idx], bin_percentages[bin_idx]) 
                   for bin_idx in bin_counts.index if not bin_is_alert[bin_idx]]
    alert_bins = [(bin_idx, bin_scores[bin_idx], bin_percentages[bin_idx]) 
                  for bin_idx in bin_counts.index if bin_is_alert[bin_idx]]
    
    # Create stable random jitter for each bin using bin_idx as seed
    # This ensures same score always appears at same X-position
    def get_jitter_x(bin_idx):
        np.random.seed(bin_idx * 1000)  # Stable seed based on bin
        return np.random.uniform(15, 85)  # Random position between 15-85%
    
    # Create figure
    fig = go.Figure()
    
    # Add normal score dots - light blue solid circles
    if normal_bins:
        normal_scores = [x[1] for x in normal_bins]
        normal_percentages = [x[2] for x in normal_bins]
        normal_x_positions = [get_jitter_x(x[0]) for x in normal_bins]
        
        # Scale dot sizes: percentage determines size
        # Min size 8, max size 50, scaled by percentage
        normal_sizes = [max(8, min(50, p * 2.5)) for p in normal_percentages]
        
        fig.add_trace(go.Scatter(
            x=normal_x_positions,
            y=normal_scores,
            mode='markers',
            marker=dict(
                size=normal_sizes,
                color='#87CEEB',  # Light blue (Sky Blue)
                line=dict(width=0),  # No border
                opacity=0.7
            ),
            name='Normal',
            hovertemplate='<b>Score: %{y:.3f}</b><br>Frequency: %{customdata:.2f}%<br><extra></extra>',
            customdata=normal_percentages
        ))
    
    # Add alert score dots - orange solid circles
    if alert_bins:
        alert_scores = [x[1] for x in alert_bins]
        alert_percentages = [x[2] for x in alert_bins]
        alert_x_positions = [get_jitter_x(x[0]) for x in alert_bins]
        
        # Scale dot sizes for alerts
        alert_sizes = [max(10, min(50, p * 2.5)) for p in alert_percentages]
        
        fig.add_trace(go.Scatter(
            x=alert_x_positions,
            y=alert_scores,
            mode='markers',
            marker=dict(
                size=alert_sizes,
                color='#FF8C00',  # Orange (Dark Orange)
                line=dict(width=0),  # No border
                opacity=0.8
            ),
            name='Alert',
            hovertemplate='<b>🚨 ALERT</b><br>Score: %{y:.3f}<br>Frequency: %{customdata:.2f}%<br><extra></extra>',
            customdata=alert_percentages
        ))
    
    # Add threshold line (horizontal)
    fig.add_hline(
        y=threshold,
        line=dict(color='#FF8C00', width=1.5),  # Orange to match alerts
        annotation_text=f"Threshold ({threshold:.2f})",
        annotation_position="right",
        annotation=dict(font=dict(size=10, color='#FF8C00', weight='bold'))
    )
    
    # Add gridlines at 0.25 intervals on Y-axis
    for y_val in [0.0, 0.25, 0.5, 0.75, 1.0]:
        if abs(y_val - threshold) > 0.01:  # Don't duplicate threshold line
            fig.add_hline(
                y=y_val,
                line=dict(color='#e8e8e8', width=0.5),  # Very light gray for subtlety
                annotation_text=f"{y_val:.2f}",
                annotation_position="left",
                annotation=dict(font=dict(size=9, color='#999999'), xshift=-10)
            )
    
    # Layout with static axes
    fig.update_layout(
        height=450,
        template="plotly_white",
        showlegend=True,
        hovermode='closest',
        xaxis_title="",  # No X-axis title (meaningless jitter)
        yaxis_title="Anomaly Score",
        margin=dict(l=60, r=20, t=30, b=40),
        font=dict(family="Arial, sans-serif", size=11),
        xaxis=dict(
            showgrid=False,  # No gridlines
            showticklabels=False,  # No tick labels
            range=[0, 100],  # Fixed range 0-100
            fixedrange=True  # Prevent zooming/panning
        ),
        yaxis=dict(
            range=[0, 1],
            showgrid=False,  # Gridlines added manually above
            dtick=0.25,
            fixedrange=True  # Prevent zooming/panning
        ),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.01,
            bgcolor='rgba(255, 255, 255, 0.9)',
            bordercolor='lightgray',
            borderwidth=1
        ),
        # Add transition for smoother animation
        transition=dict(
            duration=800,  # Slower transition for size changes
            easing='cubic-in-out'
        )
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
*Version 3.0 - Jitter-Based Distribution with Size Animation*
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
    st.markdown("### About TransGuard")
    
    st.markdown("""
    Real-time anomaly detection using:
    - **Online Learning**: Isolation Forest
    - **Welford's Algorithm**: Efficient streaming statistics
    - **Z-Score Features**: Per-sender normalization
    """)
    
    # Key Features tooltip
    with st.expander("ℹ️ Visualization Features"):
        st.markdown("""
        **Key Features:**
        - **Y-axis = Anomaly Score (0.0 to 1.0)** - vertical position shows score
        - **X-axis = Random Distribution** - horizontal spread for visual clarity (no meaning)
        - **Dot Size = Frequency** - larger dots mean more transactions at that score level
        - **Light Blue circles** - normal transactions
        - **Orange circles** - alert transactions above threshold
        - ONE dot per score level - no clutter, very clean
        - Dots stay in fixed positions - only SIZE changes over time
        - Hairline gridlines help read exact score values
        - Orange threshold line clearly separates normal from alerts
        """)
    
    # Animation Behavior tooltip
    with st.expander("ℹ️ Animation Behavior"):
        st.markdown("""
        **How the visualization updates:**
        - Dots remain in FIXED positions (both X and Y)
        - As new transactions arrive, dots smoothly GROW or SHRINK
        - **Only dot size animates** - easy to track changes
        - Larger dot = more common score; smaller dot = rare score
        - **Example:** If score 0.15 becomes more common, its dot grows
        - Time window keeps total transaction count stable
        - **Visual effect:** constellation of "breathing" dots
        - Normal scores (bottom) typically show large light blue dots
        - Alert scores (top) typically show small orange dots
        - Smooth 800ms transitions for natural pulsing effect
        """)
    
    st.markdown("""
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

# Scatter plot - Main visualization
st.markdown("### Anomaly Score Distribution")
scatter_plot = create_scatter_plot(df, st.session_state.threshold)
st.plotly_chart(scatter_plot, use_container_width=True)

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
