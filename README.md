# TERRA-BUD

TERRA-BUD is a tool for estimating costs of Terraform infrastructure deployments.

## Quick Start

### Prerequisites
- Python 3.8+
- Virtual environment

### Setup

1. **Create and activate virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables:**
   Create a `.env` file in the project root:
   ```bash
   GITHUB_CLIENT_ID=your_github_client_id
   GITHUB_CLIENT_SECRET=your_github_client_secret
   GITHUB_REDIRECT_URI=http://localhost:8080/auth/callback
   SESSION_SECRET=your-secret-session-key
   MISTRAL_API_KEY=your_mistral_api_key
   MISTRAL_MODEL=mistral-large-latest
   MISTRAL_API_BASE_URL=https://api.mistral.ai/v1
   MISTRAL_TIMEOUT=40
   ```
   
   **Important:** No spaces around `=` signs in `.env` file!

4. **Start the server:**
   ```bash
   ./start_server.sh
   ```
   
   Or manually:
   ```bash
   source venv/bin/activate
   source .env
   python -m uvicorn backend.main:app --host 0.0.0.0 --port 8080 --reload
   ```

5. **Access the application:**
   Open http://localhost:8080 in your browser

## Architecture

This is a single-page application (SPA) served entirely by the FastAPI backend:

- **Frontend:** Served at `http://localhost:8080/` (landing.html or index.html)
- **Static Files:** Served at `http://localhost:8080/static/*` (CSS, JS)
- **APIs:** Available at `http://localhost:8080/api/*`

All routing is handled client-side. The backend serves the HTML shell and handles API requests.

## Features

- **No-login estimation:** Paste Terraform code or upload files to get immediate cost estimates
- **GitHub integration:** Optional OAuth connection to analyze repositories
- **Scenario modeling:** Compare costs across regions, autoscaling, and traffic assumptions
- **Share estimates:** Generate read-only links to share estimates with your team
- **Cost insights:** AI-generated advisory insights (optional, requires API key)

## API Documentation

Once the server is running, visit:
- Swagger UI: http://localhost:8080/docs
- ReDoc: http://localhost:8080/redoc
