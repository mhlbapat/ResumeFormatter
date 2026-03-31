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

## Setup

1. Configure environment variables

Create a `.env` file in the project root (or export variables in your shell):

```bash
OPENAI_API_KEY=your_openai_api_key
# Optional if you switch providers in config/settings.yaml:
# GEMINI_API_KEY=your_gemini_key
# OLLAMA_BASE_URL=http://localhost:11434
```

2. Configure `config/settings.yaml`

Update these as needed:

- `resume.projects_path` -> path to your `profile.md` (default: `data/cv/profile.md`)
- `resume.phd_degree` -> academic track label shown on resumes (default: `Chemical Engineering`)
- `resume.candidate_name`
- `resume.contact.email`, `resume.contact.phone`, `resume.contact.location`, `resume.contact.linkedin_handle`
- `llm.provider` and `llm.model`
- `resume.static_prompt_path` -> prompt template used for resume generation (default: `prompts/resume_static_prefix.txt`)

You must also have a LaTeX distribution installed (for example TeX Live or MacTeX) with `pdflatex` available on your PATH, since the tool calls `pdflatex` to generate PDFs.

3. Tune the system prompt (recommended)

Edit the prompt template at `prompts/resume_static_prefix.txt`.

The file is loaded by `build_resume_static_prefix()` and must include the token:

`<<FULL_PROFILE_TEXT>>`

The LLM output must remain valid JSON with these keys:
`job_title, company, location, summary, skills, research_experience`.

4. Run the backend

```bash
python -m uvicorn web.app:app --reload --host 0.0.0.0 --port 8000
```

5. Enable the Chrome extension

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
