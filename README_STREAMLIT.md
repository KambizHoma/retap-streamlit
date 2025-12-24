# RETAP - Streamlit Version

Real-Time Bank Transaction Anomaly Platform converted to Streamlit.

## Files

- `app_streamlit.py` - Main Streamlit application
- `retap_core.py` - Core simulation and anomaly detection logic
- `sample_config.json` - Configuration for transaction simulator
- `requirements.txt` - Python dependencies

## Running Locally

```bash
pip install -r requirements.txt
streamlit run app_streamlit.py
```

## Key Differences from Gradio Version

### Architecture
- **State Management**: Uses `st.session_state` instead of global state objects
- **Auto-refresh**: Streamlit's `st.rerun()` replaces Gradio's timer-based updates
- **Layout**: Streamlit's sidebar vs Gradio's column-based layout

### UI Components
- **Buttons**: Separate Start/Stop buttons instead of toggle checkbox
- **Metrics**: `st.metric()` components for key statistics
- **Plots**: Direct `st.plotly_chart()` integration
- **Dataframe**: `st.dataframe()` with automatic formatting

### Streaming Behavior
- When stream is running, app auto-generates data and reruns every second
- More responsive feel due to Streamlit's reactive model
- Stop button immediately halts the stream

## Features

✅ Real-time transaction simulation
✅ Online anomaly detection with Isolation Forest
✅ Stem plot visualization (Energex style)
✅ Score distribution histogram
✅ Configurable time window and alert threshold
✅ Transaction history table
✅ Start/Stop/Step/Clear controls

## Configuration

Edit `sample_config.json` to adjust:
- `tx_per_second`: Transaction generation rate
- `num_senders`: Number of sender accounts
- `num_receivers`: Number of receiver accounts
- `burst_prob`: Probability of burst transactions
- `anomaly_prob`: Probability of anomalous transactions

## Contact

**Nippotica Corporation**
Nippofin Business Unit
nippofin@nippotica.jp
