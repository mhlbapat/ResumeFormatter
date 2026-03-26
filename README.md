# ResumeFormatter

ResumeFormatter generates tailored resume PDFs from job descriptions using a local FastAPI backend and a Chrome extension.

- Accepts a pasted job description
- Reads only `data/cv/profile.md` (configurable) as the candidate profile
- Uses an LLM to generate tailored resume content
- Renders the result to PDF and lets the extension download/open it

## Installation

1. Clone the repo

```bash
git clone https://github.com/mhlbapat/resume_formatter.git
cd resume_formatter
```

2. Create and activate a Conda environment (recommended)

```bash
conda create -n resume_formatter python=3.11 -y
conda activate resume_formatter
python -m pip install --upgrade pip
```

3. Install requirements

```bash
python -m pip install -r requirements.txt
```

4. Configure environment variables

Create a `.env` file in the project root (or export variables in your shell):

```bash
OPENAI_API_KEY=your_openai_api_key
# Optional if you switch providers in config/settings.yaml:
# GEMINI_API_KEY=your_gemini_key
# OLLAMA_BASE_URL=http://localhost:11434
```

5. Configure `config/settings.yaml`

Update these as needed:

- `resume.projects_path` -> path to your profile/project markdown (default: `data/cv/profile.md`)
- The backend reads only `profile.md` (the repo ships a template in `data/cv/profile.md`)
- `resume.phd_degree` -> academic track label shown on resumes (default: `Chemical Engineering`)
- `llm.provider` and `llm.model` -> match your selected API provider
- `resume.candidate_name` and contact fields

6. Run the backend

```bash
python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 8000
```

7. Enable the Chrome extension

1. Open Chrome and go to `chrome://extensions`.
2. Turn on **Developer mode** (top-right).
3. Click **Load unpacked**.
4. Select the folder: `resume-formatter-chrome-extension`.
5. Confirm the extension appears as **ResumeFormatter**.

The extension expects the backend at `http://localhost:8000`.

## Usage

1. Click the **ResumeFormatter** extension icon in Chrome.
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
