import tempfile
from collections import Counter
from pathlib import Path

from adwe.services.repository_clone import clone_repository
from adwe.workflows.state import WorkflowState

IGNORED_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    "node_modules",
    ".pytest_cache",
    "dist",
    "build",
    ".mypy_cache",
    ".ruff_cache",
}

LANGUAGE_BY_EXT = {
    ".py": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".go": "Go",
    ".rs": "Rust",
    ".java": "Java",
    ".rb": "Ruby",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".toml": "TOML",
    ".md": "Markdown",
    ".sql": "SQL",
    ".sh": "Shell",
}


def _is_ignored(path: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.parts)


def _relative(path: Path, repo_path: Path) -> str:
    return str(path.relative_to(repo_path))


def _detect_frameworks(files: list[Path], repo_path: Path) -> dict[str, bool]:
    relative_files = {_relative(path, repo_path) for path in files}
    file_names = {path.name for path in files}

    pyproject = next((path for path in files if path.name == "pyproject.toml"), None)
    pyproject_text = pyproject.read_text(errors="ignore").lower() if pyproject else ""

    return {
        "fastapi": "fastapi" in pyproject_text,
        "django": "django" in pyproject_text or "manage.py" in file_names,
        "flask": "flask" in pyproject_text,
        "sqlalchemy": "sqlalchemy" in pyproject_text,
        "alembic": any("migrations" in path.parts for path in files),
        "docker": "Dockerfile" in file_names or "docker-compose.yml" in file_names,
        "github_actions": any(path.startswith(".github/workflows/") for path in relative_files),
        "pytest": any(path.name.startswith("test_") and path.suffix == ".py" for path in files),
    }


def analyze_repository(state: WorkflowState):
    repository_url = state["repository_url"]

    with tempfile.TemporaryDirectory() as tmpdir:
        repo_path = Path(tmpdir) / "repo"
        clone_repository(repository_url, repo_path)

        files = [
            path
            for path in repo_path.rglob("*")
            if path.is_file() and not _is_ignored(path)
        ]

        relative_files = [_relative(path, repo_path) for path in files]

        languages = Counter(
            LANGUAGE_BY_EXT.get(path.suffix, "Other")
            for path in files
        )

        api_routes = [
            _relative(path, repo_path)
            for path in files
            if "api" in path.parts and path.suffix == ".py"
        ]

        database_models = [
            _relative(path, repo_path)
            for path in files
            if "models" in path.parts and path.suffix == ".py"
        ]

        entrypoints = [
            _relative(path, repo_path)
            for path in files
            if path.name in {"main.py", "app.py", "server.py", "asgi.py", "wsgi.py"}
        ]

        migration_files = [
            _relative(path, repo_path)
            for path in files
            if "migrations" in path.parts and path.suffix == ".py"
        ]

        test_files = [
            _relative(path, repo_path)
            for path in files
            if path.name.startswith("test_") and path.suffix == ".py"
        ]

        config_files = [
            _relative(path, repo_path)
            for path in files
            if path.name
            in {
                "pyproject.toml",
                "requirements.txt",
                "Dockerfile",
                "docker-compose.yml",
                "alembic.ini",
                ".env.example",
                "Makefile",
            }
        ]

        detected_tools = _detect_frameworks(files, repo_path)

    return {
        "repository_analysis": {
            "repository_url": repository_url,
            "file_count": len(relative_files),
            "languages": dict(languages),
            "detected_tools": detected_tools,
            "entrypoints": entrypoints,
            "api_routes": api_routes,
            "database_models": database_models,
            "migration_count": len(migration_files),
            "migration_files": migration_files[:20],
            "test_count": len(test_files),
            "test_files": test_files[:20],
            "config_files": config_files,
            "sample_files": relative_files[:50],
        }
    }
