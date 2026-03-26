# ResumeFormatter

ResumeFormatter generates tailored resume PDFs from job descriptions using a local FastAPI backend and a Chrome extension.

## What this tool does

- Accepts a job description (from the web app or Chrome extension)
- Uses your CV/profile data + LLM prompts to generate a tailored resume
- Renders the result to PDF
- Lets the Chrome extension download and open the PDF automatically

## Prerequisites

- Python 3.11+
- Google Chrome
- `pdflatex` installed and available on your `PATH` (MacTeX/TeX Live)
- An LLM API key (for example `OPENAI_API_KEY` when using OpenAI)

## Installation

From the project root:

```bash
git clone https://github.com/mhlbapat/resume_formatter.git
cd resume_formatter
```

## Create a new Conda environment (recommended)

```bash
conda create -n resume_formatter python=3.11 -y
conda activate resume_formatter
python -m pip install --upgrade pip
```

## Install requirements

```bash
python -m pip install -r requirements.txt
```

## Configure environment variables

Create a `.env` file in the project root (or export variables in your shell):

```bash
OPENAI_API_KEY=your_openai_api_key
# Optional if you switch providers in config/settings.yaml:
# GEMINI_API_KEY=your_gemini_key
# OLLAMA_BASE_URL=http://localhost:11434
```

## Configure project settings

Update `config/settings.yaml` as needed:

- `app.cv_path` -> path to your base CV PDF (default: `data/cv/Resume.pdf`)
- `resume.projects_path` -> path to your profile/project markdown (default: `data/cv/profile.md`)
- `llm.provider` and `llm.model` -> match your selected API provider
- `resume.candidate_name` and contact fields

## Run the backend

Start the FastAPI server:

```bash
python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000` to confirm the app is running.

---

## Enable the Chrome extension

1. Open Chrome and go to `chrome://extensions`.
2. Turn on **Developer mode** (top-right).
3. Click **Load unpacked**.
4. Select the folder: `resume-formatter-chrome-extension`.
5. Confirm the extension appears as **ResumeFormatter**.

Important:

- Keep the backend running at `http://localhost:8000`.
- The extension is configured to call that local backend.

---

## How to use the Chrome extension

1. Click the ResumeFormatter extension icon in Chrome.
2. Paste the full job description text into the popup text area.
3. Click **Generate & Download**.
4. Wait for processing:
   - The extension sends your text to `POST /generate_from_text`
   - The backend generates a tailored PDF
   - Chrome downloads the PDF to your Downloads folder
   - A new tab opens with the generated PDF

If generation fails:

- Make sure the backend is running on port `8000`
- Check that your API key is set correctly
- Verify `pdflatex` is installed and available in terminal
