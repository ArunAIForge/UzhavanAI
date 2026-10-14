# -*- coding: utf-8 -*-

ABOUT_MODAL_CSS = """
<style>
    /* Hide default Streamlit dialog header title to eliminate vertical gap */
    div[data-testid="stDialog"] div[data-testid="stDialogHeader"] h2,
    div[data-testid="stDialog"] div[data-testid="stDialogHeader"] p {
        display: none !important;
    }

    /* Top Bar: Title & Language Switch in one row */
    .about-dialog-top-bar {
        display: flex;
        align-items: center;
        justify-content: space-between;
        margin-top: -30px;
        margin-bottom: 12px;
        padding-right: 48px;
    }

    .about-dialog-main-heading {
        font-size: 1.15rem;
        font-weight: 800;
        color: #064e3b;
        display: flex;
        align-items: center;
        gap: 8px;
        white-space: nowrap;
    }

    @keyframes headerShimmer {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }

    .about-modal-card {
        background: linear-gradient(145deg, #ffffff 0%, #fafffc 100%);
        border: 1.5px solid #d1fae5;
        border-radius: 16px;
        padding: 14px 18px;
        margin-bottom: 12px;
        box-shadow: 0 4px 16px rgba(6, 78, 59, 0.06);
        transition: transform 0.25s cubic-bezier(0.2, 0.8, 0.2, 1), 
                    border-color 0.25s ease, 
                    box-shadow 0.25s ease;
    }
    .about-modal-card:hover {
        border-color: #34d399;
        transform: translateY(-3px);
        box-shadow: 0 10px 28px -4px rgba(6, 78, 59, 0.14), 0 0 16px rgba(16, 185, 129, 0.12);
    }

    .about-card-header {
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
        border-bottom: 1.5px dashed #bbf7d0;
        padding-bottom: 8px;
    }

    .about-card-title-animated {
        font-size: 0.96rem;
        font-weight: 800;
        background: linear-gradient(120deg, #064e3b 0%, #059669 45%, #d97706 90%, #064e3b 100%);
        background-size: 260% auto;
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        animation: headerShimmer 6s ease-in-out infinite;
        letter-spacing: -0.2px;
        display: flex;
        align-items: center;
        gap: 7px;
        text-shadow: 0 2px 10px rgba(5, 150, 105, 0.15);
    }

    .about-card-badge {
        font-size: 0.64rem;
        font-weight: 800;
        background: linear-gradient(135deg, #ecfdf5 0%, #d1fae5 100%);
        color: #065f46;
        padding: 3px 10px;
        border-radius: 999px;
        border: 1px solid #6ee7b7;
        margin-left: auto;
        box-shadow: 0 2px 6px rgba(16, 185, 129, 0.15);
        text-transform: uppercase;
        letter-spacing: 0.4px;
    }

    .about-grid-container {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(210px, 1fr));
        gap: 9px;
        margin-top: 8px;
    }

    .about-sub-chip {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-left: 3.5px solid #10b981;
        border-radius: 11px;
        padding: 8px 12px;
        font-size: 0.76rem;
        line-height: 1.45;
        box-shadow: 0 2px 6px rgba(0, 0, 0, 0.02);
        transition: transform 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
    }
    .about-sub-chip:hover {
        transform: translateY(-2px);
        border-color: #a7f3d0;
        border-left-color: #059669;
        box-shadow: 0 4px 12px rgba(6, 78, 59, 0.07);
    }
    .about-sub-chip strong {
        color: #064e3b;
        display: block;
        font-size: 0.79rem;
        margin-bottom: 2px;
    }
    .about-sub-chip p {
        margin: 0;
        color: #475569;
    }

    div[data-testid="stRadio"] > div {
        gap: 2px !important;
        background: linear-gradient(135deg, #ecfdf5 0%, #f0fdf4 100%);
        padding: 2px 4px;
        border-radius: 999px;
        border: 1.5px solid #86efac;
        box-shadow: 0 2px 8px rgba(16, 185, 129, 0.16);
        justify-content: flex-end;
    }
    div[data-testid="stRadio"] label {
        padding: 2px 9px !important;
        border-radius: 999px;
        font-weight: 800 !important;
        font-size: 0.72rem !important;
        transition: all 0.2s ease;
    }
    div[data-testid="stRadio"] label:hover {
        background: rgba(16, 185, 129, 0.12);
    }

    .about-modal-bottom-spacer {
        height: 38px;
        width: 100%;
    }
</style>
"""

ABOUT_HTML_EN = """
<div class="about-modal-card">
    <div class="about-card-header">
        <span class="about-card-title-animated">🎯 Project Mission</span>
        <span class="about-card-badge">Mission</span>
    </div>
    <div style="font-size: 0.83rem; color: #1e293b; line-height: 1.65;">
        <strong>Uzhavan AI</strong> is an intelligent agriculture assistant designed to guide Tamil Nadu farmers through state government welfare schemes, subsidies, and modern irrigation practices in clear Tamil and English.
    </div>
</div>

<div class="about-modal-card">
    <div class="about-card-header">
        <span class="about-card-title-animated">🌟 Core Features</span>
        <span class="about-card-badge">Features</span>
    </div>
    <div class="about-grid-container">
        <div class="about-sub-chip">
            <strong>💬 Bilingual Interface</strong>
            <p>Natural conversational guidance in Tamil and English with instant scheme answers.</p>
        </div>
        <div class="about-sub-chip">
            <strong>📋 Automated Application Dossier</strong>
            <p>Structured scheme benefits, eligibility, and required docs with downloadable SVG tokens.</p>
        </div>
        <div class="about-sub-chip">
            <strong>🎙️ Voice Playback (TTS)</strong>
            <p>Concise speech audio summaries for convenient, on-the-go listening.</p>
        </div>
        <div class="about-sub-chip">
            <strong>🌾 Field &amp; Water Calculator</strong>
            <p>Instant calculations for SRI seeds, AWD water savings, and micro-irrigation subsidies.</p>
        </div>
    </div>
</div>

<div class="about-modal-card">
    <div class="about-card-header">
        <span class="about-card-title-animated">🤖 Model &amp; Architecture</span>
        <span class="about-card-badge">Architecture</span>
    </div>
    <div class="about-grid-container">
        <div class="about-sub-chip">
            <strong>⚡ Backend Engine</strong>
            <p>FastAPI (High-Performance Async REST &amp; SSE Stream API)</p>
        </div>
        <div class="about-sub-chip">
            <strong>🧠 Language Model</strong>
            <p>GPT-4o-mini (Zero-Temperature Grounding)</p>
        </div>
        <div class="about-sub-chip">
            <strong>📐 Embedding Model</strong>
            <p>text-embedding-3-small (1536-dimensional vectors)</p>
        </div>
        <div class="about-sub-chip">
            <strong>🗄️ Dense Vector Database</strong>
            <p>FAISS Vector Index (storage/faiss_index/)</p>
        </div>
        <div class="about-sub-chip">
            <strong>🔍 Lexical Retrieval</strong>
            <p>BM25 Indexing for precise keyword and scheme matching</p>
        </div>
        <div class="about-sub-chip">
            <strong>🎯 Cross-Encoder Reranker</strong>
            <p>FlashRank (ms-marco-TinyBERT-L-2-v2)</p>
        </div>
    </div>
</div>

<div class="about-modal-card">
    <div class="about-card-header">
        <span class="about-card-title-animated">🚀 Performance Optimizations</span>
        <span class="about-card-badge">Speed &amp; Async</span>
    </div>
    <div class="about-grid-container">
        <div class="about-sub-chip">
            <strong>⚡ FastAPI Async Stream</strong>
            <p>Server-sent event token streaming with minimal latency overhead.</p>
        </div>
        <div class="about-sub-chip">
            <strong>🚜💨 Smooth Typewriter</strong>
            <p>Fluid progressive text reveal with an active forward tractor pointer.</p>
        </div>
        <div class="about-sub-chip">
            <strong>🧵 Non-Blocking Async Tasks</strong>
            <p>Parallel TTS synthesis and dossier preparation via ThreadPoolExecutor.</p>
        </div>
        <div class="about-sub-chip">
            <strong>💾 In-Memory Query Cache</strong>
            <p>Bounded 256-entry backend response cache for repeated queries.</p>
        </div>
    </div>
</div>

<div class="about-modal-card" style="margin-bottom: 0;">
    <div class="about-card-header">
        <span class="about-card-title-animated">🏛️ Verified Grounding Sources</span>
        <span class="about-card-badge">Grounding</span>
    </div>
    <div style="font-size: 0.79rem; color: #334155; line-height: 1.75;">
        <div>🎓 <strong>TNAU Agritech Portal:</strong> Tamil Nadu Agricultural University advisories &amp; crop guidelines</div>
        <div>📜 <strong>Government Orders (GOs):</strong> Official Agriculture &amp; Farmers Welfare Department scheme manuals</div>
        <div>💧 <strong>Uzhavan App &amp; PMKSY:</strong> Departmental drip/sprinkler irrigation protocols &amp; subsidy rules</div>
    </div>
</div>
"""

ABOUT_HTML_TA = """
<div class="about-modal-card">
    <div class="about-card-header">
        <span class="about-card-title-animated">🎯 திட்டத்தின் நோக்கம்</span>
        <span class="about-card-badge">Mission</span>
    </div>
    <div style="font-size: 0.83rem; color: #1e293b; line-height: 1.65;">
        <strong>உழவன் AI</strong> என்பது தமிழ்நாடு அரசு வேளாண்மை மற்றும் உழவர் நலத்துறையின் முக்கிய திட்டங்கள், மானியங்கள் மற்றும் பாசன கையேடுகளை எளிய தமிழில் விவசாயிகளுக்கு வழிகாட்ட உருவாக்கப்பட்ட விவேக வழிகாட்டியாகும்.
    </div>
</div>

<div class="about-modal-card">
    <div class="about-card-header">
        <span class="about-card-title-animated">🌟 முக்கிய சிறப்பம்சங்கள்</span>
        <span class="about-card-badge">Core Features</span>
    </div>
    <div class="about-grid-container">
        <div class="about-sub-chip">
            <strong>💬 இருமொழி வழிகாட்டல்</strong>
            <p>எளிய தமிழ் மற்றும் ஆங்கிலத்தில் உடனடி அரசு வேளாண் ஆலோசனை.</p>
        </div>
        <div class="about-sub-chip">
            <strong>📋 தானியங்கி விண்ணப்ப அட்டை</strong>
            <p>திட்டம், மானிய விகிதம், தகுதி மற்றும் தேவையான ஆவணங்களுடன் உடனடி SVG டோக்கன்.</p>
        </div>
        <div class="about-sub-chip">
            <strong>🎙️ குரல் வழி வாசிப்பு</strong>
            <p>பதில்களின் சுருக்கத்தை எளிதாகக் கேட்கும் தமிழ்/ஆங்கில TTS குரல் ஒலிபரப்பு.</p>
        </div>
        <div class="about-sub-chip">
            <strong>🌾 ஊடாடும் நிலக் கணக்கீடு</strong>
            <p>SRI விதை தேவை, AWD நீர் சேமிப்பு மற்றும் சொட்டு நீர் மானிய மதிப்பீடு.</p>
        </div>
    </div>
</div>

<div class="about-modal-card">
    <div class="about-card-header">
        <span class="about-card-title-animated">🤖 மாதிரி &amp; தொழில்நுட்ப கட்டமைப்பு</span>
        <span class="about-card-badge">Architecture</span>
    </div>
    <div class="about-grid-container">
        <div class="about-sub-chip">
            <strong>⚡ Backend Engine</strong>
            <p>FastAPI (High-Performance Async REST &amp; SSE Stream)</p>
        </div>
        <div class="about-sub-chip">
            <strong>🧠 Language Model</strong>
            <p>GPT-4o-mini (Zero-Temperature Grounding)</p>
        </div>
        <div class="about-sub-chip">
            <strong>📐 Embedding Model</strong>
            <p>text-embedding-3-small (1536 Dimensions)</p>
        </div>
        <div class="about-sub-chip">
            <strong>🗄️ Dense Vector Database</strong>
            <p>FAISS Vector Index (Local Storage: storage/faiss_index/)</p>
        </div>
        <div class="about-sub-chip">
            <strong>🔍 Lexical Retrieval</strong>
            <p>BM25 Indexing (Exact Keyword Matching)</p>
        </div>
        <div class="about-sub-chip">
            <strong>🎯 Cross-Encoder Reranker</strong>
            <p>FlashRank (ms-marco-TinyBERT-L-2-v2)</p>
        </div>
    </div>
</div>

<div class="about-modal-card">
    <div class="about-card-header">
        <span class="about-card-title-animated">🚀 செயல்திறன் மேம்பாடுகள்</span>
        <span class="about-card-badge">Optimizations</span>
    </div>
    <div class="about-grid-container">
        <div class="about-sub-chip">
            <strong>⚡ FastAPI Async Stream</strong>
            <p>உடனடி SSE நிகழ்வுகள் மூலம் குறைந்த தாமதப் பதில் (Low Latency).</p>
        </div>
        <div class="about-sub-chip">
            <strong>🚜💨 Smooth Typewriter</strong>
            <p>இழுவை இயந்திர (Tractor) குறியீட்டுடன் கூடிய தட்டச்சு அசைவூட்டம்.</p>
        </div>
        <div class="about-sub-chip">
            <strong>🧵 Non-Blocking Async Tasks</strong>
            <p>ThreadPoolExecutor மூலம் தனித்தனியாக உருவாகும் ஆடியோ &amp; ஆவணம்.</p>
        </div>
        <div class="about-sub-chip">
            <strong>💾 In-Memory Query Cache</strong>
            <p>மீண்டும் கேட்கப்படும் கேள்விகளுக்கு உடனடிப் பதிலளிக்கும் 256-எண்ட்ரி கேச்.</p>
        </div>
    </div>
</div>

<div class="about-modal-card" style="margin-bottom: 0;">
    <div class="about-card-header">
        <span class="about-card-title-animated">🏛️ சரிபார்க்கப்பட்ட தகவல் ஆதாரங்கள்</span>
        <span class="about-card-badge">Verified Sources</span>
    </div>
    <div style="font-size: 0.79rem; color: #334155; line-height: 1.75;">
        <div>🎓 <strong>TNAU Agritech Portal:</strong> தமிழ்நாடு வேளாண்மைப் பல்கலைக்கழக போர்டல் &amp; பயிர் வழிகாட்டிகள்</div>
        <div>📜 <strong>அரசாணைகள் (GOs):</strong> வேளாண்மை &amp; உழவர் நலத்துறை அதிகாரப்பூர்வ திட்ட கையேடுகள்</div>
        <div>💧 <strong>உழவன் செயலி &amp; PMKSY:</strong> சொட்டு நீர் பாசனம் &amp; மானிய வழிகாட்டு நெறிமுறைகள்</div>
    </div>
</div>
"""