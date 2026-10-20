"""Build small local git repositories with known, planted issues (for the GitHub review tests)."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

FAKE_AWS = "AKIA" + "J5Q7R2X9LM4TB8ZK"            # split so this file itself never trips a scanner
FAKE_OPENAI = "sk-proj-" + "a1B2c3D4e5F6g7H8i9J0kLmNoPqRsTuVwXyZ0123456789abcdEF"
FAKE_MONGO = "mongodb+srv://asha:" + "S3cr3tPassw0rd" + "@cluster0.ab12c.mongodb.net/app"
FIREBASE_WEB_KEY = "AIza" + "SyDq3xV8_kLmN0pQrStUvWxYz1234567890"


def _git(repo: Path, *args: str, date: str | None = None) -> None:
    env = {**os.environ, "GIT_AUTHOR_NAME": "Asha Verma", "GIT_AUTHOR_EMAIL": "asha@example.com",
           "GIT_COMMITTER_NAME": "Asha Verma", "GIT_COMMITTER_EMAIL": "asha@example.com"}
    if date:
        env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env)


def _write(repo: Path, files: dict[str, str]) -> None:
    for rel, content in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")


def _commit(repo: Path, msg: str, files: dict[str, str] | None = None, day: int = 1, remove: list[str] | None = None) -> None:
    if files:
        _write(repo, files)
    for r in remove or []:
        _git(repo, "rm", "-q", r)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", msg, date=f"2025-0{1 + day // 28}-{1 + day % 28:02d}T10:00:00")


def _init(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q", "-b", "main")
    return path


GOOD_README = """# DevConnect

Real-time Q&A platform for student developers. **Live:** https://devconnect-demo.vercel.app

![Home page](docs/screenshot-home.png)
![Chat demo](docs/demo.gif)

## Tech stack
React, Node.js, Express, MongoDB, Socket.io

## Getting started
```bash
git clone https://github.com/asha/devconnect.git
cd devconnect
npm install
cp .env.example .env
npm run dev
```

## Running tests
```bash
npm test
```
"""


def build_all(root: Path) -> dict[str, dict]:
    """Returns {name: {"path": Path, "expect": {...}}}."""
    root.mkdir(parents=True, exist_ok=True)
    repos: dict[str, dict] = {}

    r = _init(root / "good_fullstack")
    _commit(r, "feat: scaffold express server and react client", {
        ".gitignore": "node_modules/\n.env\ndist/\n", "README.md": GOOD_README, ".env.example": "MONGO_URI=\nJWT_SECRET=\n",
        "package.json": '{"name":"devconnect","scripts":{"test":"jest"},"devDependencies":{"jest":"^29.0.0"}}',
        "src/server/index.js": "const express = require('express');\nconst app = express();\napp.listen(process.env.PORT || 4000);\n",
        "src/client/App.jsx": "export default function App() {\n  return <main>Hello</main>;\n}\n",
        "docs/screenshot-home.png": "png", "docs/demo.gif": "gif"}, day=1)
    _commit(r, "feat(auth): add JWT login and signup routes", {"src/server/auth.js": "module.exports = {};\n"}, day=3)
    _commit(r, "test: cover auth routes with jest", {"src/server/auth.test.js": "test('ok', () => expect(1).toBe(1));\n"}, day=5)
    _commit(r, "ci: run tests on every push", {".github/workflows/ci.yml": "on: push\njobs: {}\n"}, day=7)
    _commit(r, "fix(chat): reconnect socket after network drop", {"src/server/chat.js": "module.exports = {};\n"}, day=9)
    repos["good_fullstack"] = {"path": r, "expect": {"readme": True, "setup": True, "screenshots": True, "secrets": 0,
                                                      "junk": 0, "tests": True, "good_commits": True}}

    r = _init(root / "no_readme")
    _commit(r, "update", {"main.py": "print('hello')\n", "utils.py": "def f():\n    return 1\n"}, day=1)
    _commit(r, "update", {"main.py": "print('hello world')\n"}, day=2)
    _commit(r, "final", {"utils.py": "def f():\n    return 2\n"}, day=3)
    repos["no_readme"] = {"path": r, "expect": {"readme": False, "secrets": 0, "good_commits": False, "tests": False}}

    r = _init(root / "readme_no_setup")
    _commit(r, "Initial commit", {"README.md": "# weather-app\n", "index.html": "<h1>Weather</h1>", "script.js": "fetch('x')\n"}, day=1)
    _commit(r, "Update script.js", {"script.js": "fetch('y')\n"}, day=2)
    repos["readme_no_setup"] = {"path": r, "expect": {"readme": True, "setup": False, "screenshots": False, "secrets": 0,
                                                       "good_commits": False}}

    r = _init(root / "aws_key_committed")
    _commit(r, "feat: upload images to S3", {
        "README.md": GOOD_README.replace("DevConnect", "SnapShare"),
        "src/config.js": f"module.exports = {{\n  region: 'ap-south-1',\n  accessKeyId: '{FAKE_AWS}',\n}};\n",
        ".gitignore": "node_modules\n"}, day=1)
    repos["aws_key_committed"] = {"path": r, "expect": {"secrets_min": 1, "rule": "aws_access_key"}}

    r = _init(root / "secret_in_history")
    _commit(r, "feat: add chatbot using OpenAI", {"README.md": "# Chatbot\n\n## Setup\n```\npip install -r requirements.txt\n```\n",
                                                  "bot.py": "import os\n", ".env": f"OPENAI_API_KEY={FAKE_OPENAI}\nDEBUG=true\n",
                                                  "requirements.txt": "openai\n"}, day=1)
    _commit(r, "chore: remove .env from repo", remove=[".env"], files={".gitignore": ".env\n"}, day=2)
    repos["secret_in_history"] = {"path": r, "expect": {"secrets_min": 1, "history": True}}

    r = _init(root / "node_modules_committed")
    _commit(r, "added files", {
        "README.md": "# Todo app\nRun `npm install` then `npm start`.\n",
        "package.json": '{"name":"todo"}', "index.js": "console.log('todo');\nconsole.log('debug');\n",
        "node_modules/lodash/index.js": "module.exports={}\n", "node_modules/lodash/package.json": "{}",
        "dist/bundle.js": "!function(){}()\n", ".DS_Store": "x"}, day=1)
    repos["node_modules_committed"] = {"path": r, "expect": {"junk_min": 2, "gitignore": False}}

    r = _init(root / "web_upload")
    files = {f"file{i}.py": f"x = {i}\n" for i in range(18)}
    files["README.md"] = "# Library management\n"
    _commit(r, "Add files via upload", files, day=1)
    repos["web_upload"] = {"path": r, "expect": {"web_upload": True, "good_commits": False, "organized": False}}

    r = _init(root / "firebase_and_mongo")
    _commit(r, "feat: firebase auth and mongo persistence", {
        "README.md": "# Notes\n\n## Install\n```\nnpm i && npm run dev\n```\n",
        "src/firebase.js": f"const firebaseConfig = {{\n  apiKey: \"{FIREBASE_WEB_KEY}\",\n  authDomain: \"notes.firebaseapp.com\",\n}};\n",
        "server/db.js": f"const uri = '{FAKE_MONGO}';\n", ".gitignore": "node_modules\n"}, day=1)
    repos["firebase_and_mongo"] = {"path": r, "expect": {"secrets_min": 1, "rule": "db_uri", "info_rule": "google_api_key"}}

    r = _init(root / "python_ml")
    long_fn = "def train(df):\n" + "".join(f"    x{i} = df['c{i}'] * 2\n    print(x{i})\n" for i in range(50)) + "    return df\n"
    _commit(r, "feat: train crop disease classifier", {
        "README.md": "# CropDoc\n\n![demo](assets/demo.png)\n\n## Setup\n```bash\npip install -r requirements.txt\npython train.py\n```\n",
        "requirements.txt": "torch\npytest\n", "train.py": long_fn, "tests/test_train.py": "def test_x():\n    assert True\n",
        "assets/demo.png": "png", ".gitignore": "__pycache__/\n"}, day=1)
    _commit(r, "perf: cache preprocessed tensors to cut epoch time", {"cache.py": "CACHE = {}\n"}, day=4)
    repos["python_ml"] = {"path": r, "expect": {"tests": True, "long_function": True, "secrets": 0}}

    r = _init(root / "default_cra_readme")
    _commit(r, "Initialize project using Create React App", {
        "README.md": "# Getting Started with Create React App\n\nThis project was bootstrapped with [Create React App](https://github.com/facebook/create-react-app).\n",
        "src/App.js": "fetch('http://localhost:5000/api/items')\n", "package.json": '{"name":"shop"}', ".gitignore": "node_modules\n"}, day=1)
    _commit(r, "changes", {"src/App.js": "fetch('http://localhost:5000/api/items/1')\n"}, day=2)
    repos["default_cra_readme"] = {"path": r, "expect": {"default_template": True, "localhost": True, "good_commits": False}}

    return repos
