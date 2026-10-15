# ⚡ DealScout — Agentic E-Commerce Radar & Arbitrage Hunter

> An intelligent, autonomous deal-hunting agent that extracts real-time discounts across Flipkart, Myntra, and TataCLiQ, validates in-stock sizes, and uses LLM intelligence to judge whether a deal is a **STEAL**, **WORTH IT**, or **SKIP**.

---

## 🚀 Features

- **🤖 3-Stage Agentic Pipeline**:
  - **Stage 1 (Intent Extraction)**: Uses Gemini Flash to parse free-form natural language into structured search parameters (brands, target sizes, price bands, discount thresholds).
  - **Stage 2 (Targeted Crawl & Hydration)**: Dual-phase scrapers that search listings in bulk and hydrate PDP state only for qualified candidates.
  - **Stage 3 (LLM Deal Judgment)**: Evaluates deal value, price-to-spec ratio, gender fit, and product category to assign a verdict (`STEAL` / `WORTH_IT` / `SKIP`) with a 1-sentence reason.
- **⚡ Bypass Dynamic Pricing & WOW Deals**: Decodes SSR states (`window.__INITIAL_STATE__`) to surface Flipkart VIP/Plus bank offers and Tata Neu NeuCoin discounts.
- **📏 Strict Size Stock Verification**: Rejects phantom or out-of-stock listings by parsing variant matrixes directly from server state.
- **🖥️ Modern Web UI & Terminal UI**:
  - Interactive web dashboard (Sanic backend) with real-time **Agent Scout** tab.
  - Form & raw JSON config editors.
  - Background scheduler daemon.
  - Native macOS banner notifications & Telegram bot alerts.

---

## 📦 Quick Setup

### 1. Clone & Install Dependencies

```bash
git clone https://github.com/<your-username>/deal-scout.git
cd deal-scout

pip install -r requirements.txt
playwright install
```

### 2. Configure Environment

Copy template and add your Gemini API key:

```bash
cp config.example.json config.json
echo "GEMINI_API_KEY=AIzaSy..." > .env
```

---

## 🎮 Usage

### 1. Run via Agent CLI
Ask in plain English:
```bash
python3 agent.py "Nike running shoes under 5000, size 10, at least 40% off"
```

### 2. Launch the Web Dashboard
```bash
python3 server.py
```
Open **[http://localhost:8080](http://localhost:8080)** in your browser:
- Navigate to **"Agent Scout"** tab.
- Enter any natural search query.
- View real-time parsed filters, deals grid, and AI judgment badges.

### 3. Run Standard Scheduled Pipeline
```bash
python3 pipeline.py --query "adidas sl 72"
```

---

## 🏛️ Architecture

```
User Query ("Nike running shoes < 5k size 10")
      │
      ▼
┌──────────────────────────────────────────────┐
│ Stage 1: Intent Extraction (Gemini Flash)    │
│ -> queries, brands, sizes, price, discount   │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ Stage 2: Ingestion & Verification Engine     │
│ -> Search Listing Parse (Flipkart/Myntra/CLiQ)│
│ -> In-stock Size & WOW Offer Hydration       │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ Stage 3: LLM Deal Judgment                   │
│ -> Evaluates gender, category, real value    │
│ -> Emits STEAL / WORTH_IT / SKIP + reason    │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
         Rich Terminal & Web UI Dashboard
```

---

## 📄 License
MIT License
