"""NCSA / University of Illinois brand styling for the Streamlit dashboard.

Colors: Illini Blue #13294B, Illini Orange #FF5F05 (the official UIUC palette,
also used across NCSA properties).
"""
from __future__ import annotations

ILLINI_BLUE = "#13294B"
ILLINI_ORANGE = "#FF5F05"

_CSS = f"""
<style>
  /* Branded top banner */
  .ncsa-banner {{
    background: linear-gradient(90deg, {ILLINI_BLUE} 0%, #1d3a6b 100%);
    border-bottom: 4px solid {ILLINI_ORANGE};
    padding: 1.0rem 1.4rem;
    border-radius: 8px;
    margin-bottom: 1.2rem;
    color: #ffffff;
  }}
  .ncsa-banner h1 {{
    color: #ffffff !important;
    font-size: 1.6rem; margin: 0; font-weight: 700;
  }}
  .ncsa-banner .sub {{ color: #cdd6e6; font-size: 0.9rem; margin-top: 0.2rem; }}
  .ncsa-banner .badge {{
    display: inline-block; background: {ILLINI_ORANGE}; color: {ILLINI_BLUE};
    font-weight: 700; padding: 0.05rem 0.5rem; border-radius: 4px;
    font-size: 0.75rem; margin-right: 0.4rem; letter-spacing: 0.02em;
  }}
  /* Tabs: orange active underline */
  .stTabs [aria-selected="true"] {{ color: {ILLINI_BLUE} !important; }}
  .stTabs [data-baseweb="tab-highlight"] {{ background-color: {ILLINI_ORANGE} !important; }}
  /* Primary buttons in Illini orange */
  .stButton > button[kind="primary"], .stFormSubmitButton > button {{
    background-color: {ILLINI_ORANGE}; border-color: {ILLINI_ORANGE}; color: {ILLINI_BLUE};
    font-weight: 600;
  }}
  /* Metric labels */
  [data-testid="stMetricValue"] {{ color: {ILLINI_BLUE}; }}
  /* Headers */
  h2, h3 {{ color: {ILLINI_BLUE}; }}

  /* "Powered by Lumen" sticker */
  .lumen-sticker {{
    display: flex; align-items: center; gap: 0.7rem;
    background: linear-gradient(100deg, {ILLINI_ORANGE} 0%, #ff8a3d 100%);
    color: {ILLINI_BLUE};
    border: 2px solid {ILLINI_BLUE};
    border-radius: 999px;
    padding: 0.5rem 1.1rem;
    margin: 0.2rem 0 1.1rem 0;
    font-weight: 800; font-size: 1.02rem; letter-spacing: 0.02em;
    box-shadow: 0 3px 10px rgba(19,41,75,0.25);
    width: fit-content;
    animation: lumenpulse 2.6s ease-in-out infinite;
  }}
  .lumen-sticker .spark {{ font-size: 1.3rem; }}
  .lumen-sticker a {{ color: {ILLINI_BLUE}; text-decoration: underline; }}
  .lumen-sticker .small {{ font-weight: 600; font-size: 0.8rem; opacity: 0.85; }}
  @keyframes lumenpulse {{
    0%, 100% {{ box-shadow: 0 3px 10px rgba(19,41,75,0.25); transform: translateY(0); }}
    50% {{ box-shadow: 0 6px 18px rgba(255,95,5,0.55); transform: translateY(-1px); }}
  }}
</style>
"""

_BANNER = """
<div class="ncsa-banner">
  <span class="badge">NCSA</span><span class="badge">ILLINOIS</span>
  <h1>Delta / DeltaAI Citation Tracker</h1>
  <div class="sub">National Center for Supercomputing Applications &middot;
  University of Illinois Urbana-Champaign</div>
</div>
"""


def apply(st) -> None:
    """Inject brand CSS. Call once near the top of the app."""
    st.markdown(_CSS, unsafe_allow_html=True)


def banner(st) -> None:
    """Render the branded header banner."""
    st.markdown(_BANNER, unsafe_allow_html=True)


def lumen_sticker(st, model: str = "") -> None:
    """Render the prominent 'Powered by NCSA Lumen LLM' sticker."""
    model_note = f'<span class="small">· {model}</span>' if model else ""
    st.markdown(
        f"""
        <div class="lumen-sticker">
          <span class="spark">⚡</span>
          <span>POWERED BY THE NCSA LUMEN LLM SERVICE</span>
          {model_note}
        </div>
        """,
        unsafe_allow_html=True,
    )
