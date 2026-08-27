# Life Graph AI

## Run the web app

The project is a FastAPI application that serves the static frontend from
`frontend/`.

- Replit workflow: `Start application`
- Command: `python -m uvicorn backend.main:app --host 0.0.0.0 --port 5000`
- Preview: open the Replit web preview after the workflow starts

## Dependencies

Python dependencies are listed in `backend/requirements.txt`.

## Gemini AI features

The app can read `GEMINI_API_KEY` from Replit Secrets. Without it, the web
interface and account flow still load, but Gemini-powered document processing,
semantic search, chat, and career analysis will not work.

To add it, open the Replit Secrets panel, create a secret named
`GEMINI_API_KEY`, and restart the `Start application` workflow.