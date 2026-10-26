# RepoPilot-AI

RepoPilot-AI is a code assistant that helps developers understand code, find relevant files, investigate bugs, and get AI-generated suggestions for improving their code.

## Features

- **Repository Analysis:** Explore and understand a codebase.
- **Code Search:** Find code using keywords or semantic search.
- **AI Code Assistant:** Ask questions about your code and get answers with source references.
- **Bug Analysis:** Identify possible causes of bugs and get suggested fixes.
- **GitHub Integration:** Connect public GitHub repositories.
- **Search History:** Save previous searches and analysis.
- **User Authentication:** Register, log in, and manage your session.

## Tech Stack

- **Frontend:** Streamlit
- **Backend:** Django, Django REST Framework
- **Database:** PostgreSQL, Django ORM
- **Code Parsing:** Tree-sitter
- **Search:** BM25, Sentence Transformers, FAISS
- **AI:** LLM API
- **Integration:** GitHub REST API
- **Testing:** pytest
- **Deployment:** Docker, Docker Compose

## How It Works

1. Connect a public GitHub repository.
2. RepoPilot-AI downloads and analyzes the repository's code.
3. Search for code using keywords or semantic similarity.
4. Ask questions about the code or investigate bugs.
5. Review AI-generated explanations and suggested fixes.

## Project Structure

```text
RepoPilot-AI/
├── frontend/
│   ├── app.py
│   ├── api_client.py
│   ├── components.py
│   ├── styles.css
│   ├── requirements.txt
│   └── Dockerfile
├── backend/
│   ├── manage.py
│   ├── Dockerfile
│   └── ...
├── docker-compose.yml
├── .env.example
├── .gitignore
└── README.md
```

## Run the Project Locally

**Requirements:** Docker Desktop and Git.

1. Clone the repository:

   ```bash
   git clone https://github.com/navyagupta20/RepoPilot.git
   ```

2. Open the project folder:

   ```bash
   cd RepoPilot
   ```

3. Configure the required environment variables in your `.env` file using `.env.example` as a guide.

4. Start the application:

   ```bash
   docker compose up --build
   ```

5. Open the application in your browser:

   **Frontend:** http://localhost:8501

   **Backend:** http://localhost:8000

To stop the application, run:

```bash
docker compose down
```

## Important Notes

- Keep API keys, passwords, and the `.env` file private.
- AI-generated fixes should be reviewed before applying them.
- The application does not execute imported repository code.

## Future Improvements

- Support more programming languages.
- Improve bug detection and code explanations.
- Add more code analysis features.