<div align="center">

<br/>

```
██████╗ ██████╗  █████╗ ███████╗████████╗     █████╗ ██╗
██╔══██╗██╔══██╗██╔══██╗██╔════╝╚══██╔══╝    ██╔══██╗██║
██║  ██║██████╔╝███████║█████╗     ██║       ███████║██║
██║  ██║██╔══██╗██╔══██║██╔══╝     ██║       ██╔══██║██║
██████╔╝██║  ██║██║  ██║██║        ██║       ██║  ██║██║
╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝        ╚═╝       ╚═╝  ╚═╝╚═╝
```

### **The AI Platform for Engineering Drawings**
*Analyze. Convert. Check. All in one place.*

<br/>

<img src="https://img.shields.io/badge/version-1.0-f97316?style=for-the-badge&labelColor=0b0b0b"/>
<img src="https://img.shields.io/badge/Python-3.10+-f97316?style=for-the-badge&labelColor=0b0b0b"/>
<img src="https://img.shields.io/badge/Streamlit-1.x-f97316?style=for-the-badge&labelColor=0b0b0b"/>
<img src="https://img.shields.io/badge/GPT--4o-Vision-f97316?style=for-the-badge&labelColor=0b0b0b"/>
<img src="https://img.shields.io/badge/SolidWorks-Add--in-f97316?style=for-the-badge&labelColor=0b0b0b"/>

<br/><br/>

[![Live App](https://img.shields.io/badge/🚀_Launch_App-draftaii.streamlit.app-f97316?style=for-the-badge&labelColor=0b0b0b)](https://draftaii.streamlit.app)
[![Website](https://img.shields.io/badge/🌐_Website-draftai.cloud-ffffff?style=for-the-badge&labelColor=0b0b0b)](https://draftai.cloud)
[![Add-in](https://img.shields.io/badge/⬇_SolidWorks_Add--in-v1.0-ffffff?style=for-the-badge&labelColor=0b0b0b)](https://github.com/Rishi24-alt/DraftAI-Addin/releases/latest)

</div>

---

## What is Draft AI?

Draft AI is a full-stack AI platform built for mechanical engineers. Upload any engineering drawing — or open any sketch in SolidWorks — and get an instant, intelligent analysis.

No more manual checking. No more missed dimensions. No more drawings bouncing back from manufacturers.

```
Engineering Drawing / SolidWorks Sketch
              ↓
         Draft AI
              ↓
  ┌───────────────────────────┐
  │  Dimensions detected      │
  │  GD&T reviewed            │
  │  Standards checked        │
  │  Cost estimated           │
  │  Manufacturability scored │
  │  Missing dims flagged     │
  │  BOM extracted            │
  └───────────────────────────┘
              ↓
    Actionable report. Instantly.
```

---

## Platform Overview

Draft AI has two main parts:

### 🌐 Web Application
A Streamlit-powered app where engineers upload drawings and get full AI analysis — accessible from any browser, no installation needed.

### ⚙️ SolidWorks Add-in
A native Windows add-in that lives inside SolidWorks — press `Ctrl+Shift+A` in any sketch and get instant feedback without leaving your CAD environment.

---

## Features

### Web App — Drawing Analysis

| # | Feature | Description |
|---|---------|-------------|
| 01 | 📐 **Dimension Detection** | Extracts all dimensions, tolerances, and units from any drawing automatically |
| 02 | 🎯 **GD&T Analysis** | Full geometric dimensioning and tolerancing review per ASME Y14.5 |
| 03 | ✅ **Standards Checker** | Scored compliance report across 8 categories — ASME Y14.5, ISO GPS, BS 8888 |
| 04 | 📋 **BOM Generator** | Extracts Bill of Materials from assembly drawings — export to Excel or PDF |
| 05 | 💰 **Cost Estimation** | AI-powered cost estimate based on material, complexity, and manufacturing method |
| 06 | 🏭 **Manufacturability Score** | 0–100 DFM score — catches machining problems before you send to production |
| 07 | ⚠️ **Design Concerns** | CRITICAL / WARNING / INFO severity flags on real design issues |
| 08 | 🔄 **Revision Comparison** | Upload two revisions — get a diff of exactly what changed between Rev A and Rev B |
| 09 | 📦 **Batch Analysis** | Analyze up to 5 drawings at once — single Excel or PDF export |
| 10 | 🏷️ **Title Block Extraction** | Reads and structures all title block metadata automatically |
| 11 | 📊 **Tolerance Stack-Up** | Calculates cumulative tolerances across a dimension chain |
| 12 | 🔍 **Missing Dimension Detection** | Flags under-dimensioned features before release |

### SolidWorks Add-in — Live Sketch Analysis

| Feature | Description |
|---------|-------------|
| ⚡ **Ctrl+Shift+A Hotkey** | Global hotkey — works even when SolidWorks has focus |
| 🔍 **Sketch Analyzer** | Reads segment data from SW API — tells you exactly what's underdefined |
| ✅ **Fully Defined Detection** | Instantly detects when your sketch is fully defined — no false alerts |
| 🔔 **Toast Notifications** | Hover-to-pause, scrollable, auto-dismiss overlay in SolidWorks |
| 🌐 **HTTP API** | Local server on port 7432 — integrates with any external tool |

### 3D → 2D Converter

| Feature | Description |
|---------|-------------|
| 📁 **STEP / STP Support** | Upload any STEP file — Draft AI opens it in SolidWorks automatically |
| 📷 **4 View Export** | Front, Top, Side, and Isometric views exported as PNG |
| 📏 **Dimension Extraction** | Exact bounding box dimensions extracted from the 3D model |
| 📄 **A3 Drawing Sheet** | Professional PDF with title block, drawing number, revision, and all 4 views |

---

## Tech Stack

```
Frontend          Streamlit (Python)
AI Engine         OpenAI GPT-4o Vision API
Add-in            C# · .NET 4.8 · SolidWorks Interop API
PDF Export        ReportLab
Excel Export      openpyxl
Image Processing  PIL / Pillow
Proxy Server      Flask (Railway)
Standards         ASME Y14.5 · ISO GPS · BS 8888
```

---

## Project Structure

```
draft-ai/
├── app.py                  # Main Streamlit application
├── utils.py                # All AI analysis functions
├── cad_converter.py        # SolidWorks add-in HTTP client
├── pdf_generator.py        # PDF export engine
├── draftai_setup.py        # Add-in configuration utility
├── requirements.txt        # Python dependencies
├── index.html              # Landing page (draftai.cloud)
└── drawing_library/        # Saved drawings (local, gitignored)
```

> The SolidWorks Add-in lives in a separate repo:
> **[github.com/Rishi24-alt/DraftAI-Addin](https://github.com/Rishi24-alt/DraftAI-Addin)**

---

## Getting Started

### Web App (Local)

```bash
# Clone
git clone https://github.com/Rishi24-alt/draft-ai.git
cd draft-ai

# Install dependencies
pip install -r requirements.txt

# Run
streamlit run app.py
```

Open `http://localhost:8501`

### Environment Variables

Create a `.env` file:

```env
# Optional — app uses Draft AI cloud proxy by default
OPENAI_API_KEY=sk-your-key-here
```

> No API key needed for the hosted version at [draftaii.streamlit.app](https://draftaii.streamlit.app)

### SolidWorks Add-in

```
1. Download DraftAI_Addin_V1.0.zip from Releases
2. Extract to any permanent folder
3. Right-click install.bat → Run as Administrator
4. SolidWorks → Tools → Add-Ins → check Draft AI → OK
5. Open any sketch → press Ctrl+Shift+A
```

---

## Roadmap

- [x] Drawing analysis — dimensions, GD&T, materials, manufacturing
- [x] Standards compliance checker — ASME / ISO / BS 8888
- [x] BOM generator with Excel/PDF export
- [x] Batch analysis — up to 5 drawings
- [x] Cost estimation & manufacturability scoring
- [x] SolidWorks add-in with Ctrl+Shift+A hotkey
- [x] 3D → 2D converter — STEP to professional drawing sheet
- [x] Cloud proxy — no API key needed for users
- [ ] Shhh... i'm cooking it 

---

## Why Draft AI?

Most engineering AI tools are either too generic or locked behind expensive enterprise software. Draft AI is built specifically for the engineer sitting at the desk — the student getting underdefined sketches, the freelancer whose drawings get bounced back, the small team that can't afford a Dassault 3DEXPERIENCE license.

> *"I built this because I was tired of doing the same repetitive checks every time I needed a drawing."*

---

## Built By

**Rishi Raj** — Mechanical Engineering Student & Builder

[![LinkedIn](https://img.shields.io/badge/LinkedIn-Rishi_Raj-0077b5?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/in/rishii24/)
[![Website](https://img.shields.io/badge/Website-draftai.cloud-f97316?style=for-the-badge&labelColor=0b0b0b)](https://draftai.cloud)
[![App](https://img.shields.io/badge/Live_App-draftaii.streamlit.app-f97316?style=for-the-badge&labelColor=0b0b0b)](https://draftaii.streamlit.app)

---

<div align="center">

**Made with ♥ · Powered by GPT-4o Vision · Built for Engineers**

<sub>If Draft AI saved you time, drop a ⭐ — it means a lot.</sub>

</div>

