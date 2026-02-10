# Gemini 3 Hackathon Demo · Novel Agents

This is a demo of a multi-agent writing system:
- **Create**: Group chat-style creation with collaboration among multiple agents.
- **Preview**: Bookshelf-style preview of chapter content.
- **Settings**: Configuration for models and word counts.

## How to Run

```bash
cd gemini-hackathon
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Open in browser: `http://localhost:8000`

## Key Notes

- Agent collaboration is pipeline-based (single-turn). The human user is responsible for assessing style and writing quality.
- The Checker only verifies format and completeness.
- Output files are located in `gemini-hackathon/output/<project_slug>/`.

## Model Configuration

Defaults to reading `gemini-hackathon/models_config.json` (Gemini 3 Flash/Pro configuration).
You can specify the Model ID for each role in `Settings`.

Example environment variable:

```bash
export GEMINI_API_KEY=...
```

Alternatively, you can try this project on Google AI Studio: https://ai.studio/apps/drive/1Klc1mW5IMlrUUYneSHshe0bX6AuEJ6n1?fullscreenApplet=true