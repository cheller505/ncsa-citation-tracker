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

  /* ---- "Powered by NCSA Lumen" radiant sticker ---- */
  .lumen-wrap {{ padding: 0.15rem 0 1.25rem 0; }}
  .lumen-sticker {{
    position: relative;
    display: inline-flex; align-items: center; gap: 0.65rem;
    padding: 0.62rem 1.55rem;
    border-radius: 999px;
    font-weight: 900; font-size: 1.06rem; letter-spacing: 0.07em;
    color: #2b1400;
    background: linear-gradient(100deg, #ff5f05, #ffae42, #ffe39e, #ffae42, #ff5f05);
    background-size: 280% 100%;
    border: 1.5px solid rgba(255,255,255,0.55);
    text-shadow: 0 1px 0 rgba(255,255,255,0.45);
    overflow: hidden;
    animation: lumen-flow 6s ease infinite, lumen-halo 3s ease-in-out infinite;
  }}
  /* sweeping light shine across the pill */
  .lumen-sticker::before {{
    content: ""; position: absolute; top: 0; left: -65%;
    width: 55%; height: 100%;
    background: linear-gradient(100deg, transparent, rgba(255,255,255,0.9), transparent);
    transform: skewX(-20deg);
    animation: lumen-shine 3.6s ease-in-out infinite;
  }}
  .lumen-sticker .txt {{ position: relative; z-index: 1; }}
  .lumen-sticker .bolt {{
    position: relative; z-index: 1; font-size: 1.3rem;
    filter: drop-shadow(0 0 6px rgba(255,255,255,0.95));
    animation: lumen-spark 1.7s ease-in-out infinite;
  }}
  @keyframes lumen-flow {{
    0% {{ background-position: 0% 50%; }}
    50% {{ background-position: 100% 50%; }}
    100% {{ background-position: 0% 50%; }}
  }}
  @keyframes lumen-halo {{
    0%, 100% {{ box-shadow: 0 0 0 2px rgba(255,255,255,0.4) inset,
                            0 0 16px rgba(255,138,61,0.7), 0 0 30px rgba(255,95,5,0.45); }}
    50% {{ box-shadow: 0 0 0 2px rgba(255,255,255,0.6) inset,
                       0 0 30px rgba(255,176,77,0.95), 0 0 64px rgba(255,95,5,0.72); }}
  }}
  @keyframes lumen-shine {{ 0% {{ left: -65%; }} 60% {{ left: 135%; }} 100% {{ left: 135%; }} }}
  @keyframes lumen-spark {{ 0%, 100% {{ transform: scale(1); opacity: 1; }}
                            50% {{ transform: scale(1.28); opacity: 0.85; }} }}
  @media (prefers-reduced-motion: reduce) {{
    .lumen-sticker, .lumen-sticker::before, .lumen-sticker .bolt {{ animation: none; }}
  }}
</style>
"""

_BANNER = """
<div class="ncsa-banner">
  <span class="badge">NCSA</span><span class="badge">ILLINOIS</span>
  <h1>NCSA Research Computing Citation Tracker</h1>
  <div class="sub">Citations of NCSA &amp; University of Illinois research computing
  &amp; data resources</div>
</div>
"""


def apply(st) -> None:
    """Inject brand CSS. Call once near the top of the app."""
    st.markdown(_CSS, unsafe_allow_html=True)


def banner(st) -> None:
    """Render the branded header banner."""
    st.markdown(_BANNER, unsafe_allow_html=True)


def lumen_sticker(st, model: str = "") -> None:  # model kept for back-compat, unused
    """Render the prominent, radiant 'Powered by NCSA Lumen' sticker."""
    st.markdown(
        """
        <div class="lumen-wrap">
          <div class="lumen-sticker">
            <span class="bolt">⚡</span>
            <span class="txt">POWERED BY THE NCSA LUMEN LLM SERVICE</span>
            <span class="bolt">✨</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
