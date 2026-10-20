"""Skill ontology shared by resume parsing, LinkedIn review, job matching and interview planning.

Each skill has a canonical spelling (also used for the "tech term casing" check), a category
and aliases. Skills that are also ordinary English words ("react", "express", "go", "spring")
are marked ambiguous and only counted when they appear in a technical context.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Skill:
    name: str
    category: str
    aliases: tuple[str, ...] = ()
    context_aliases: tuple[str, ...] = ()   # only counted in a technical context ("rest", "node", "spring")
    ambiguous: bool = False                 # the canonical name itself is an ordinary word ("React", "Express")


def _s(name: str, category: str, *aliases: str, ambiguous: bool = False) -> Skill:
    strong = tuple(a for a in aliases if not a.startswith("~"))
    weak = tuple(a[1:] for a in aliases if a.startswith("~"))
    return Skill(name, category, strong, weak, ambiguous)


SKILLS: list[Skill] = [
    # ---------------------------------------------------------------- languages
    _s("Python", "language", "python3"),
    _s("Java", "language", "core java", "java 8", "java 17"),
    _s("C++", "language", "cpp", "c plus plus"),
    _s("C", "language", ambiguous=True),
    _s("C#", "language", "csharp", "c sharp"),
    _s("JavaScript", "language", "javascript", "js", "es6", "ecmascript", "vanilla js"),
    _s("TypeScript", "language", "typescript", "~ts"),
    _s("Go", "language", "golang", ambiguous=True),
    _s("Rust", "language", ambiguous=True),
    _s("Kotlin", "language"),
    _s("Swift", "language", ambiguous=True),
    _s("Dart", "language", ambiguous=True),
    _s("PHP", "language"),
    _s("Ruby", "language", ambiguous=True),
    _s("R", "language", ambiguous=True),
    _s("Scala", "language"),
    _s("SQL", "language", "structured query language"),
    _s("Bash", "language", "shell scripting", "shell script", "bash scripting"),
    _s("Solidity", "language"),
    _s("MATLAB", "language"),
    # ---------------------------------------------------------------- frontend
    _s("HTML", "frontend", "html5"),
    _s("CSS", "frontend", "css3"),
    _s("React", "frontend", "reactjs", "react.js", "react js", ambiguous=True),
    _s("Next.js", "frontend", "nextjs", "next js"),
    _s("Angular", "frontend", "angularjs", "angular.js"),
    _s("Vue.js", "frontend", "vue", "vuejs", "vue js", "nuxt"),
    _s("Svelte", "frontend", "sveltekit"),
    _s("Redux", "frontend", "redux toolkit", "rtk"),
    _s("Tailwind CSS", "frontend", "tailwind", "tailwindcss"),
    _s("Bootstrap", "frontend"),
    _s("Material UI", "frontend", "mui", "material-ui"),
    _s("jQuery", "frontend", "jquery"),
    _s("Sass", "frontend", "scss"),
    _s("Vite", "frontend"),
    _s("Webpack", "frontend"),
    _s("Three.js", "frontend", "threejs"),
    _s("Responsive Design", "frontend", "responsive web design", "mobile-first design"),
    # ---------------------------------------------------------------- backend
    _s("Node.js", "backend", "nodejs", "node js", "~node"),
    _s("Express.js", "backend", "expressjs", "express js", "express", ambiguous=True),
    _s("Django", "backend", "django rest framework", "drf"),
    _s("Flask", "backend", ambiguous=True),
    _s("FastAPI", "backend", "fast api"),
    _s("Spring Boot", "backend", "springboot", "~spring", "spring framework", "spring mvc"),
    _s("Hibernate", "backend", "jpa"),
    _s("ASP.NET", "backend", ".net", "dotnet", ".net core", "asp.net core"),
    _s("Laravel", "backend"),
    _s("Ruby on Rails", "backend", "~rails"),
    _s("NestJS", "backend", "nest.js", "nestjs"),
    _s("REST APIs", "backend", "rest api", "rest apis", "restful api", "restful apis", "~rest", "restful services", "api development"),
    _s("GraphQL", "backend", "graphql"),
    _s("gRPC", "backend", "grpc"),
    _s("WebSockets", "backend", "websocket", "socket.io", "socketio"),
    _s("Microservices", "backend", "microservice", "micro-services", "microservices architecture"),
    _s("Authentication", "backend", "jwt", "oauth", "oauth2", "~auth"),
    _s("System Design", "backend", "low level design", "high level design", "lld", "hld"),
    _s("Kafka", "backend", "apache kafka"),
    _s("RabbitMQ", "backend", "rabbit mq"),
    # ---------------------------------------------------------------- databases
    _s("MySQL", "database", "mysql"),
    _s("PostgreSQL", "database", "postgres", "postgresql", "psql"),
    _s("MongoDB", "database", "mongo", "mongodb", "mongoose"),
    _s("Redis", "database"),
    _s("NoSQL", "database", "nosql"),
    _s("SQLite", "database"),
    _s("Firebase", "database", "firestore", "firebase auth"),
    _s("Supabase", "database"),
    _s("Oracle DB", "database", "~oracle", "pl/sql", "plsql"),
    _s("DynamoDB", "database", "dynamo db"),
    _s("Cassandra", "database"),
    _s("Elasticsearch", "database", "elastic search", "elk"),
    _s("DBMS", "cs_core", "database management systems", "database management system", "rdbms"),
    _s("Prisma", "database", "prisma orm"),
    # ---------------------------------------------------------------- cloud & devops
    _s("AWS", "cloud", "amazon web services", "ec2", "s3", "aws lambda", "~lambda"),
    _s("GCP", "cloud", "google cloud", "google cloud platform"),
    _s("Azure", "cloud", "microsoft azure"),
    _s("Docker", "devops", "docker compose", "docker-compose", "containerization", "~containers"),
    _s("Kubernetes", "devops", "k8s", "kubectl", "helm"),
    _s("CI/CD", "devops", "ci cd", "continuous integration", "continuous deployment", "github actions", "jenkins", "gitlab ci"),
    _s("Terraform", "devops", "infrastructure as code", "iac"),
    _s("Linux", "devops", "unix", "ubuntu"),
    _s("Nginx", "devops"),
    _s("Vercel", "cloud"),
    _s("Netlify", "cloud"),
    _s("Heroku", "cloud"),
    _s("Render", "cloud", ambiguous=True),
    _s("Prometheus", "devops", "grafana"),
    _s("Ansible", "devops"),
    # ---------------------------------------------------------------- data / ML / AI
    _s("Machine Learning", "ml", "ml", "machine-learning"),
    _s("Deep Learning", "ml", "~dl", "neural networks", "neural network", "cnn", "cnns", "rnn", "lstm"),
    _s("NLP", "ml", "natural language processing"),
    _s("Computer Vision", "ml", "image processing", "object detection"),
    _s("LLMs", "ml", "llm", "large language models", "large language model", "generative ai", "genai", "gen ai"),
    _s("RAG", "ml", "retrieval augmented generation", "retrieval-augmented generation"),
    _s("LangChain", "ml", "langchain", "langgraph", "llamaindex"),
    _s("Prompt Engineering", "ml"),
    _s("Vector Databases", "ml", "vector database", "pinecone", "faiss", "chromadb", "~chroma", "weaviate", "pgvector"),
    _s("OpenAI API", "ml", "openai", "gpt api", "chatgpt api"),
    _s("Hugging Face", "ml", "huggingface", "~transformers"),
    _s("TensorFlow", "ml", "tensorflow", "keras"),
    _s("PyTorch", "ml", "pytorch", "~torch"),
    _s("scikit-learn", "ml", "sklearn", "scikit learn"),
    _s("Pandas", "data", ambiguous=True),
    _s("NumPy", "data", "numpy"),
    _s("Matplotlib", "data", "matplotlib", "seaborn", "plotly"),
    _s("OpenCV", "ml", "opencv"),
    _s("Jupyter", "data", "jupyter notebook", "jupyter notebooks", "google colab", "colab"),
    _s("Streamlit", "ml", "gradio"),
    _s("Statistics", "data", "statistical analysis", "probability", "hypothesis testing", "a/b testing"),
    _s("Data Visualization", "data", "data viz", "~dashboards", "dashboarding"),
    _s("Power BI", "data", "powerbi"),
    _s("Tableau", "data"),
    _s("Excel", "data", "ms excel", "microsoft excel", "advanced excel", "spreadsheets", ambiguous=True),
    _s("Spark", "data", "apache spark", "pyspark", ambiguous=True),
    _s("Hadoop", "data"),
    _s("ETL", "data", "data pipelines", "data pipeline", "airflow", "apache airflow"),
    _s("Data Analysis", "data", "data analytics", "exploratory data analysis", "eda"),
    # ---------------------------------------------------------------- mobile
    _s("Android", "mobile", "android development", "android studio"),
    _s("iOS", "mobile", "ios development", "swiftui", "xcode"),
    _s("Flutter", "mobile"),
    _s("React Native", "mobile", "react-native"),
    _s("Jetpack Compose", "mobile"),
    # ---------------------------------------------------------------- tools / practices
    _s("Git", "tools", "version control"),
    _s("GitHub", "tools", "github"),
    _s("Postman", "tools"),
    _s("Jira", "tools"),
    _s("Figma", "design"),
    _s("UI/UX", "design", "ui ux", "user experience", "user interface design", "ux design", "ui design"),
    _s("Agile", "practices", "scrum", "kanban"),
    _s("Unit Testing", "testing", "unit tests", "jest", "pytest", "junit", "mocha", "vitest", "testing library"),
    _s("Selenium", "testing", "cypress", "playwright"),
    _s("API Testing", "testing"),
    # ---------------------------------------------------------------- CS fundamentals
    _s("Data Structures", "cs_core", "data structures and algorithms", "dsa", "data structure"),
    _s("Algorithms", "cs_core", "algorithm design", "competitive programming", "~problem solving"),
    _s("OOP", "cs_core", "object oriented programming", "object-oriented programming", "oops"),
    _s("Operating Systems", "cs_core", "operating system", "~os"),
    _s("Computer Networks", "cs_core", "computer networking", "~networking", "~cn", "tcp/ip"),
    _s("Cybersecurity", "security", "cyber security", "information security", "network security", "owasp", "penetration testing"),
    _s("Blockchain", "web3", "web3", "ethereum", "smart contracts"),
]

# Casing fixes for common mis-spellings of tech terms. key = wrong form (lowercase); value = correct form.
EXTRA_CASING = {
    "javascript": "JavaScript", "typescript": "TypeScript", "github": "GitHub", "gitlab": "GitLab",
    "nodejs": "Node.js", "node.js": "Node.js", "reactjs": "React", "react.js": "React", "nextjs": "Next.js",
    "next.js": "Next.js", "expressjs": "Express.js", "mongodb": "MongoDB", "mysql": "MySQL",
    "postgresql": "PostgreSQL", "jquery": "jQuery", "numpy": "NumPy", "tensorflow": "TensorFlow",
    "pytorch": "PyTorch", "opencv": "OpenCV", "graphql": "GraphQL", "fastapi": "FastAPI", "leetcode": "LeetCode",
    "hackerrank": "HackerRank", "codechef": "CodeChef", "geeksforgeeks": "GeeksforGeeks", "linkedin": "LinkedIn",
    "youtube": "YouTube", "html": "HTML", "css": "CSS", "html5": "HTML5", "css3": "CSS3", "sql": "SQL", "nosql": "NoSQL",
    "aws": "AWS", "gcp": "GCP", "api": "API", "apis": "APIs", "json": "JSON", "ios": "iOS", "macos": "macOS",
    "vscode": "VS Code", "springboot": "Spring Boot", "powerbi": "Power BI", "tailwindcss": "Tailwind CSS",
    "scikit-learn": "scikit-learn", "dbms": "DBMS", "oops": "OOP", "ci/cd": "CI/CD", "ui/ux": "UI/UX",
    "devops": "DevOps", "kubernetes": "Kubernetes", "docker": "Docker", "firebase": "Firebase", "redis": "Redis",
    "django": "Django", "python": "Python", "java": "Java", "kotlin": "Kotlin", "linux": "Linux", "figma": "Figma",
    "postman": "Postman", "jira": "Jira", "redux": "Redux", "webpack": "Webpack", "angular": "Angular",
    "vue.js": "Vue.js", "vuejs": "Vue.js", "jwt": "JWT", "oauth": "OAuth", "restful": "RESTful", "llm": "LLM",
    "llms": "LLMs", "nlp": "NLP", "genai": "GenAI", "langchain": "LangChain", "chatgpt": "ChatGPT", "openai": "OpenAI",
    "matplotlib": "Matplotlib", "seaborn": "Seaborn", "jupyter": "Jupyter", "tableau": "Tableau", "kafka": "Kafka",
    "netlify": "Netlify", "vercel": "Vercel", "heroku": "Heroku", "nginx": "Nginx", "ubuntu": "Ubuntu",
    "android": "Android", "flutter": "Flutter", "dart": "Dart", "golang": "Go", "c#": "C#", "c++": "C++",
    "php": "PHP", "xml": "XML", "yaml": "YAML", "http": "HTTP", "https": "HTTPS", "tcp/ip": "TCP/IP", "url": "URL",
    "dsa": "DSA", "ml": "ML", "ai": "AI", "iot": "IoT", "saas": "SaaS", "ui": "UI", "ux": "UX", "cgpa": "CGPA",
    "sgpa": "SGPA", "b.tech": "B.Tech", "btech": "B.Tech", "m.tech": "M.Tech", "mtech": "M.Tech", "bca": "BCA",
    "mca": "MCA", "pyspark": "PySpark", "huggingface": "Hugging Face", "websocket": "WebSocket", "websockets": "WebSockets",
"three.js": "Three.js", "d3.js": "D3.js", "supabase": "Supabase", "prisma": "Prisma",
}
# Words that are tech terms only in context; don't flag their casing in prose.
AMBIGUOUS_CASING = {"python", "java", "docker", "redis", "django", "flutter", "dart", "android", "angular", "redux",
                    "kotlin", "linux", "figma", "jira", "postman", "kafka", "tableau", "ubuntu", "nginx", "heroku",
                    "firebase", "webpack", "jupyter", "seaborn", "matplotlib", "api", "apis", "ui", "ux", "ai", "ml",
                    "url", "http", "https", "json", "xml", "yaml", "netlify", "vercel", "kubernetes"}


ROLES: dict[str, dict] = {
    "sde": {
        "title": "Software Development Engineer",
        "synonyms": ["software engineer", "software developer", "sde", "software development engineer", "developer",
                     "programmer", "engineering intern", "software intern", "graduate engineer", "associate software engineer"],
        "core": ["Data Structures", "Algorithms", "OOP", "DBMS", "Operating Systems", "Git", "SQL"],
        "any_of": [["Java", "C++", "Python", "JavaScript", "Go"]],
        "nice": ["System Design", "REST APIs", "Linux", "Computer Networks", "Unit Testing", "Docker"],
    },
    "frontend": {
        "title": "Frontend Developer",
        "synonyms": ["frontend", "front-end", "front end", "ui developer", "react developer", "web developer"],
        "core": ["JavaScript", "React", "HTML", "CSS", "Git", "Responsive Design"],
        "any_of": [],
        "nice": ["TypeScript", "Next.js", "Redux", "Tailwind CSS", "Unit Testing", "REST APIs", "Figma", "Vite"],
    },
    "backend": {
        "title": "Backend Developer",
        "synonyms": ["backend", "back-end", "back end", "api developer", "server-side", "node developer",
                     "java developer", "python developer", "golang developer"],
        "core": ["REST APIs", "SQL", "Git", "Data Structures"],
        "any_of": [["Node.js", "Spring Boot", "Django", "FastAPI", "Flask", "Express.js", "Go", "ASP.NET"],
                   ["PostgreSQL", "MySQL", "MongoDB"]],
        "nice": ["Docker", "Redis", "System Design", "AWS", "Microservices", "Unit Testing", "Linux", "Kafka", "Authentication"],
    },
    "fullstack": {
        "title": "Full Stack Developer",
        "synonyms": ["full stack", "full-stack", "fullstack", "mern", "mean stack", "web developer", "software engineer - web"],
        "core": ["JavaScript", "React", "Node.js", "REST APIs", "HTML", "CSS", "Git"],
        "any_of": [["MongoDB", "PostgreSQL", "MySQL"]],
        "nice": ["TypeScript", "Next.js", "Express.js", "Docker", "AWS", "Redux", "Tailwind CSS", "Authentication", "Unit Testing"],
    },
    "data_science": {
        "title": "Data Scientist / ML Engineer",
        "synonyms": ["data scientist", "data science", "machine learning", "ml engineer", "ai/ml", "ml intern",
                     "deep learning", "research intern", "applied scientist", "computer vision", "nlp engineer"],
        "core": ["Python", "Machine Learning", "Pandas", "NumPy", "SQL", "Statistics"],
        "any_of": [["scikit-learn", "TensorFlow", "PyTorch"]],
        "nice": ["Deep Learning", "NLP", "Computer Vision", "LLMs", "Data Visualization", "Matplotlib", "Jupyter",
                 "Hugging Face", "Docker", "Git"],
    },
    "genai": {
        "title": "Generative AI Engineer",
        "synonyms": ["generative ai", "genai", "llm engineer", "ai engineer", "prompt engineer", "ai developer", "ai application"],
        "core": ["Python", "LLMs", "RAG", "Prompt Engineering", "REST APIs"],
        "any_of": [["LangChain", "OpenAI API", "Hugging Face"]],
        "nice": ["Vector Databases", "FastAPI", "PyTorch", "Docker", "NLP", "Git", "AWS"],
    },
    "data_analyst": {
        "title": "Data Analyst",
        "synonyms": ["data analyst", "business analyst", "analytics", "bi developer", "mis analyst", "data analytics"],
        "core": ["SQL", "Excel", "Data Analysis", "Statistics", "Data Visualization"],
        "any_of": [["Power BI", "Tableau"], ["Python", "R"]],
        "nice": ["Pandas", "ETL", "Matplotlib"],
    },
    "devops": {
        "title": "DevOps / Cloud Engineer",
        "synonyms": ["devops", "cloud engineer", "site reliability", "sre", "platform engineer", "infrastructure", "cloud"],
        "core": ["Linux", "Docker", "CI/CD", "Git", "Bash"],
        "any_of": [["AWS", "GCP", "Azure"]],
        "nice": ["Kubernetes", "Terraform", "Nginx", "Prometheus", "Ansible", "Python", "Computer Networks"],
    },
    "mobile": {
        "title": "Mobile App Developer",
        "synonyms": ["android", "ios", "mobile", "flutter", "react native", "app developer"],
        "core": ["Git", "REST APIs"],
        "any_of": [["Kotlin", "Java", "Flutter", "React Native", "Swift"], ["Android", "iOS", "Flutter", "React Native"]],
        "nice": ["Firebase", "Jetpack Compose", "Dart", "Unit Testing", "UI/UX"],
    },
    "qa": {
        "title": "QA / Test Engineer",
        "synonyms": ["qa", "quality assurance", "test engineer", "sdet", "automation tester", "tester"],
        "core": ["Selenium", "API Testing", "Unit Testing", "Postman", "SQL"],
        "any_of": [["Java", "Python", "JavaScript"]],
        "nice": ["Jira", "Agile", "CI/CD", "Git"],
    },
    "uiux": {
        "title": "UI/UX Designer",
        "synonyms": ["ui/ux", "ux designer", "ui designer", "product designer", "interaction designer"],
        "core": ["Figma", "UI/UX"],
        "any_of": [],
        "nice": ["HTML", "CSS", "Responsive Design", "JavaScript"],
    },
    "security": {
        "title": "Security Engineer",
        "synonyms": ["security", "cybersecurity", "soc analyst", "penetration tester", "security analyst"],
        "core": ["Cybersecurity", "Computer Networks", "Linux"],
        "any_of": [["Python", "Bash", "C"]],
        "nice": ["Operating Systems", "AWS", "Docker"],
    },
}

TECH_CONTEXT_WORDS = {
    "api", "apis", "backend", "frontend", "database", "deployed", "framework", "library", "stack", "developed",
    "built", "using", "with", "server", "app", "application", "web", "skills", "technologies", "tools", "languages",
}


def _alias_pattern(alias: str) -> str:
    esc = re.escape(alias)
    return rf"(?<![A-Za-z0-9+#.@/]){esc}(?![A-Za-z0-9+#]|\.[A-Za-z0-9])"


def _compile(aliases) -> re.Pattern | None:
    aliases = sorted({a.lower() for a in aliases if a}, key=len, reverse=True)
    if not aliases:
        return None
    return re.compile("|".join(_alias_pattern(a) for a in aliases), re.I)


SHORT_CASE_SENSITIVE = {"C", "R", "Go"}


@lru_cache(maxsize=1)
def _matchers() -> list[tuple[Skill, re.Pattern | None, re.Pattern | None, re.Pattern | None]]:
    """(skill, strong pattern, context-only pattern, case-sensitive short-name pattern)."""
    out = []
    for skill in SKILLS:
        short = None
        names = [*skill.aliases]
        if skill.name in SHORT_CASE_SENSITIVE:
            short = re.compile(rf"(?<![A-Za-z0-9+#/.\-]){re.escape(skill.name)}(?![A-Za-z0-9+#/]|\.[A-Za-z])")
        else:
            names.append(skill.name)
        out.append((skill, _compile(names), _compile(skill.context_aliases), short))
    return out


def extract_skills(text: str, technical_context: bool = False) -> list[str]:
    """Return canonical skill names found in `text`, in order of first appearance.

    `technical_context=True` (skills sections, tech-stack lines, job descriptions) also allows
    ambiguous names ("React", "Express", "Go") and context-only aliases ("REST", "node").
    In ordinary prose those only count when written with capitals next to other tech words.
    """
    if not text:
        return []
    found: dict[str, int] = {}
    tokens = set(re.findall(r"[a-z][a-z0-9.+#/-]*", text.lower()))
    matchers = _matchers()
    # pass 1: unambiguous names establish whether this prose is technical
    for skill, strong, _weak, _short in matchers:
        if strong is not None and not skill.ambiguous:
            m = strong.search(text)
            if m:
                found[skill.name] = m.start()
    prose_context = bool(found) or bool(tokens & TECH_CONTEXT_WORDS)
    for skill, strong, weak, short in matchers:
        if skill.name in found:
            continue
        position = None
        if strong is not None and skill.ambiguous:
            m = strong.search(text)
            if m and (technical_context or (prose_context and not m.group(0).islower())):
                position = m.start()
        if position is None and weak is not None:
            m = weak.search(text)
            if m and (technical_context or (prose_context and not m.group(0).islower())):
                position = m.start()
        if position is None and short is not None and technical_context:
            m = short.search(text)
            if m:
                position = m.start()
        if position is not None:
            found[skill.name] = position
    return [name for name, _ in sorted(found.items(), key=lambda kv: kv[1])]


def skill_category(name: str) -> str:
    for skill in SKILLS:
        if skill.name == name:
            return skill.category
    return "other"


GENERIC_ROLE_WORDS = {"developer", "programmer", "software engineer", "software developer", "engineering intern",
                      "software intern", "graduate engineer", "web developer", "associate software engineer"}


def role_from_text(text: str | None) -> str:
    """Map a free-text target role ("MERN stack intern", "SDE") to a role profile id."""
    if not text:
        return "sde"
    low = text.lower()
    best, best_score = "sde", 0.0
    for role_id, role in ROLES.items():
        for syn in role["synonyms"]:
            if re.search(rf"(?<![a-z]){re.escape(syn)}(?![a-z])", low):
                score = len(syn) * (0.4 if syn in GENERIC_ROLE_WORDS else 1.0)
                if score > best_score:
                    best, best_score = role_id, score
    return best


def role_skill_weights(role_id: str) -> dict[str, float]:
    role = ROLES.get(role_id, ROLES["sde"])
    weights = {s: 1.0 for s in role["core"]}
    for group in role["any_of"]:
        for s in group:
            weights.setdefault(s, 0.8)
    for s in role["nice"]:
        weights.setdefault(s, 0.5)
    return weights


def role_gap(role_id: str, skills: list[str]) -> dict:
    """Which core skills for the role are present / missing."""
    role = ROLES.get(role_id, ROLES["sde"])
    have = set(skills)
    missing_core = [s for s in role["core"] if s not in have]
    missing_groups = [group for group in role["any_of"] if not (set(group) & have)]
    missing_nice = [s for s in role["nice"] if s not in have]
    total = len(role["core"]) + len(role["any_of"])
    covered = total - len(missing_core) - len(missing_groups)
    return {
        "role": role["title"],
        "coverage": round(covered / total, 3) if total else 1.0,
        "missing_core": missing_core,
        "missing_any_of": missing_groups,
        "missing_nice": missing_nice[:6],
        "matched": sorted(have & set(role_skill_weights(role_id))),
    }
