from .models import SkillResult, SkillDef

METADATA = {
    "name": "deploy_helper",
    "version": "2.0.0",
    "category": "deployment",
    "description": "Generates deployment config files and documentation for web, API, and static projects targeting cloud, edge, or localhost.",
}

_VALID_PROJECT_TYPES = ("web", "api", "static")
_VALID_TARGETS = ("cloud", "edge", "localhost")

_DEFAULT_PORT = 8080
_DEFAULT_RUNTIME = "python:3.11"
_DEFAULT_REGION = "us-central1"


def _env_template(config: dict) -> str:
    port = config.get("port", _DEFAULT_PORT)
    runtime = config.get("runtime", _DEFAULT_RUNTIME)
    region = config.get("region", _DEFAULT_REGION)
    lines = [
        f"APP_PORT={port}",
        f"APP_RUNTIME={runtime}",
        f"APP_REGION={region}",
        "APP_ENV=production",
        "APP_LOG_LEVEL=info",
        "DATABASE_URL=postgresql://user:pass@host:5432/dbname",
        "REDIS_URL=redis://host:6379/0",
        "SECRET_KEY=change-me-to-a-random-value",
        "API_KEY=your-api-key-here",
    ]
    if config.get("cors_origin"):
        lines.append(f"CORS_ALLOWED_ORIGINS={config['cors_origin']}")
    if config.get("workers"):
        lines.append(f"APP_WORKERS={config['workers']}")
    return "\n".join(lines)


def _health_check_section(project_type: str, port: int) -> str:
    endpoint = "/health" if project_type == "api" else "/api/health"
    lines = [
        "## Health Check",
        "",
        f"Endpoint: {endpoint}",
        "Method: GET",
        "Expected status: 200",
        "Response body:",
        '```json',
        '{ "status": "ok", "uptime": 12345, "version": "1.0.0" }',
        '```',
        "",
        "Docker HEALTHCHECK directive:",
        f"HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD curl -f http://localhost:{port}{endpoint} || exit 1",
        "",
        "Kubernetes liveness/readiness probes:",
        "```yaml",
        "livenessProbe:",
        "  httpGet:",
        f"    path: {endpoint}",
        f"    port: {port}",
        "  initialDelaySeconds: 10",
        "  periodSeconds: 30",
        "readinessProbe:",
        "  httpGet:",
        f"    path: {endpoint}",
        f"    port: {port}",
        "  initialDelaySeconds: 5",
        "  periodSeconds: 10",
        "```",
    ]
    return "\n".join(lines)


def _generate_localhost(project_type: str, config: dict) -> dict:
    port = config.get("port", _DEFAULT_PORT)
    runtime = config.get("runtime", _DEFAULT_RUNTIME)
    workers = config.get("workers", 2)

    dockerfile_lines = [
        f"FROM {runtime}",
        "WORKDIR /app",
        "COPY requirements.txt .",
        "RUN pip install --no-cache-dir -r requirements.txt",
        "COPY . .",
        f"EXPOSE {port}",
        f"CMD [\"gunicorn\", \"--bind\", \"0.0.0.0:{port}\", \"--workers\", \"{workers}\", \"app:app\"]",
    ]

    compose_lines = [
        "version: '3.8'",
        "services:",
        "  app:",
        "    build: .",
        f"    ports:",
        f"      - \"{port}:{port}\"",
        "    env_file:",
        "      - .env",
        "    volumes:",
        "      - .:/app",
        "    restart: unless-stopped",
        "  redis:",
        "    image: redis:7-alpine",
        "    ports:",
        "      - \"6379:6379\"",
    ]

    if project_type == "web":
        compose_lines += [
            "  db:",
            "    image: postgres:15-alpine",
            "    ports:",
            "      - \"5432:5432\"",
            "    environment:",
            "      POSTGRES_DB: appdb",
            "      POSTGRES_USER: user",
            "      POSTGRES_PASSWORD: pass",
        ]

    start_sh_lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        f"export APP_PORT={port}",
        "export APP_ENV=development",
        "echo 'Starting local development server on port {port}...'",
        "if command -v gunicorn &>/dev/null; then",
        f"  exec gunicorn --bind 0.0.0.0:{port} --reload app:app",
        "elif command -v uvicorn &>/dev/null; then",
        f"  exec uvicorn app:app --host 0.0.0.0 --port {port} --reload",
        "else",
        f"  exec python -m app --port {port}",
        "fi",
    ]

    return {
        "Dockerfile": "\n".join(dockerfile_lines),
        "docker-compose.yml": "\n".join(compose_lines),
        "start.sh": "\n".join(start_sh_lines),
    }


def _generate_cloud(project_type: str, config: dict) -> dict:
    port = config.get("port", _DEFAULT_PORT)
    runtime = config.get("runtime", _DEFAULT_RUNTIME)
    region = config.get("region", _DEFAULT_REGION)
    workers = config.get("workers", 2)

    procfile_lines = {
        "web": f"web: gunicorn --bind 0.0.0.0:{port} --workers {workers} app:app",
        "api": f"web: uvicorn app:app --host 0.0.0.0 --port {port} --workers {workers}",
        "static": "web: python -m http.server 8080",
    }

    app_yaml_lines = [
        f"runtime: {runtime.split(':')[0]}",
        f"env: flex",
        "",
        "automatic_scaling:",
        "  min_num_instances: 1",
        "  max_num_instances: 3",
        "",
        "resources:",
        "  cpu: 1",
        "  memory_gb: 1",
        "  disk_size_gb: 10",
        "",
        "env_variables:",
        f"  APP_PORT: '{port}'",
        "  APP_ENV: 'production'",
    ]

    dockerfile_cloud_lines = [
        f"FROM {runtime}",
        "WORKDIR /app",
        "COPY requirements.txt .",
        "RUN pip install --no-cache-dir -r requirements.txt",
        "COPY . .",
        f"EXPOSE {port}",
        f'CMD ["gunicorn", "--bind", "0.0.0.0:{port}", "--workers", "{workers}", "app:app"]',
    ]

    files = {
        "Procfile": procfile_lines[project_type],
        "app.yaml": "\n".join(app_yaml_lines),
        "Dockerfile.cloud": "\n".join(dockerfile_cloud_lines),
    }

    if project_type == "static":
        vercel_lines = [
            "{",
            '  "version": 2,',
            '  "builds": [{ "src": "public/**", "use": "@vercel/static" }],',
            '  "routes": [{ "src": "/(.*)", "dest": "/public/$1" }]',
            "}",
        ]
        files["vercel.json"] = "\n".join(vercel_lines)

    if project_type in ("web", "api"):
        eb_lines = [
            f"option_settings:",
            "  - namespace: aws:elasticbeanstalk:container:python",
            f"    option_name: WSGIPath",
            "    value: app.py",
            "  - namespace: aws:elasticbeanstalk:application:environment",
            f"    option_name: APP_PORT",
            f"    value: {port}",
        ]
        files[".ebextensions/python.config"] = "\n".join(eb_lines)

    return files


def _generate_edge(project_type: str, config: dict) -> dict:
    region = config.get("region", _DEFAULT_REGION)

    cdn_lines = [
        "## CDN Configuration",
        "",
        "### CloudFront Distribution Settings",
        "- Origin: your-origin.example.com",
        f"- Price Class: Use Only North America and Europe",
        "- Viewer Protocol Policy: redirect-to-https",
        "- Allowed Methods: GET, HEAD, OPTIONS",
        "- Cache Policy: CachingOptimized",
        "- Origin Request Policy: AllViewer",
        "",
        "### Cache Behavior Rules",
        "```json",
        "{",
        '  "PathPattern": "/api/*",',
        '  "TargetOriginId": "api-origin",',
        '  "ViewerProtocolPolicy": "redirect-to-https",',
        '  "AllowedCachedMethods": ["GET", "HEAD"],',
        '  "CacheTTL": 300',
        "}",
        "```",
    ]

    edge_fn_lines = [
        "export default {",
        "  async fetch(request, env, ctx) {",
        "    const url = new URL(request.url);",
        "",
        "    if (url.pathname.startsWith('/api/')) {",
        "      const response = await fetch(request);",
        "      const headers = new Headers(response.headers);",
        "      headers.set('Cache-Control', 'public, max-age=300');",
        "      return new Response(response.body, {",
        "        status: response.status,",
        "        headers,",
        "      });",
        "    }",
        "",
        "    return fetch(request);",
        "  },",
        "};",
    ]

    wrangler_lines = [
        'name = "edge-app"',
        f'main = "src/worker.js"',
        f'compatibility_date = "2024-01-01"',
        "",
        "[env.production]",
        f'name = "edge-app-prod"',
        f'route = "https://your-domain.com/*"',
        "",
        "[env.production.vars]",
        f'APP_REGION = "{region}"',
    ]

    files = {
        "cdn-config.md": "\n".join(cdn_lines),
        "worker.js": "\n".join(edge_fn_lines),
        "wrangler.toml": "\n".join(wrangler_lines),
    }

    if project_type == "static":
        netlify_lines = [
            "[build]",
            '  publish = "public"',
            '  command = "npm run build"',
            "",
            "[[headers]]",
            '  for = "/assets/*"',
            "  [headers.values]",
            '    Cache-Control = "public, max-age=31536000, immutable"',
            "",
            "[[headers]]",
            '  for = "/*.html"',
            "  [headers.values]",
            '    Cache-Control = "public, max-age=0, must-revalidate"',
            "",
            "[[redirects]]",
            '  from = "/*"',
            '  to = "/index.html"',
            "  status = 200",
        ]
        files["netlify.toml"] = "\n".join(netlify_lines)

    return files


def _generate_checklist(project_type: str, target: str, config: dict) -> str:
    port = config.get("port", _DEFAULT_PORT)
    items = [
        "## Deployment Checklist",
        "",
        "### Pre-Deployment",
        "- [ ] All tests passing",
        "- [ ] Environment variables configured in .env (see .env.example)",
        "- [ ] Secrets stored securely (not in code or .env committed to VCS)",
        "- [ ] Docker image builds successfully (if applicable)",
        "- [ ] Database migrations ready",
    ]

    if target == "cloud":
        items += [
            "- [ ] Cloud provider CLI installed and authenticated",
            "- [ ] Cloud resource quotas verified (CPU, memory, instances)",
            "- [ ] IAM roles and service accounts configured",
            "- [ ] SSL/TLS certificate provisioned",
            "- [ ] DNS records configured",
            "- [ ] CDN distribution created (for static assets)",
        ]

    if target == "edge":
        items += [
            "- [ ] Edge function tested locally with wrangler dev",
            "- [ ] CDN origin configured and accessible",
            "- [ ] Cache headers validated",
            "- [ ] Edge function deployment limits reviewed",
        ]

    if target == "localhost":
        items += [
            "- [ ] Docker and docker-compose installed",
            "- [ ] Port {port} available and not in use".format(port=port),
            "- [ ] .env file created from .env.example",
            "- [ ] Local services (redis, db) accessible",
        ]

    items += [
        "",
        "### Post-Deployment",
        f"- [ ] Health check endpoint responding at /health (port {port})",
        "- [ ] Application logs accessible and not showing errors",
        "- [ ] Monitoring/alerting configured",
        "- [ ] Rollback procedure documented",
        "- [ ] Load test completed (optional)",
    ]

    if project_type == "web":
        items += [
            "- [ ] Frontend assets served with correct MIME types",
            "- [ ] Client-side routing works (SPA)",
        ]
    elif project_type == "api":
        items += [
            "- [ ] API documentation accessible",
            "- [ ] Rate limiting configured",
            "- [ ] CORS headers correct for allowed origins",
        ]
    elif project_type == "static":
        items += [
            "- [ ] All static assets uploaded",
            "- [ ] Custom 404 page configured",
            "- [ ] Gzip/Brotli compression enabled",
        ]

    return "\n".join(items)


def _build_output_markdown(
    project_type: str, target: str, config: dict, files: dict
) -> str:
    port = config.get("port", _DEFAULT_PORT)
    sections = [
        "# Deployment Package",
        "",
        f"**Project Type:** {project_type}",
        f"**Target:** {target}",
        f"**Port:** {port}",
        f"**Config:** {', '.join(f'{k}={v}' for k, v in config.items()) if config else 'default'}",
        "",
        "---",
        "",
    ]

    for filename, content in files.items():
        ext = filename.rsplit(".", 1)[-1] if "." in filename else ""
        lang_map = {
            "yml": "yaml",
            "yaml": "yaml",
            "toml": "toml",
            "json": "json",
            "js": "javascript",
            "sh": "bash",
            "py": "python",
            "md": "markdown",
            "config": "yaml",
        }
        lang = lang_map.get(ext, "")
        sections.append(f"## {filename}")
        sections.append("")
        if lang:
            sections.append(f"```{lang}")
        else:
            sections.append("```")
        sections.append(content)
        sections.append("```")
        sections.append("")

    sections.append(_health_check_section(project_type, port))
    sections.append("")
    sections.append(_generate_checklist(project_type, target, config))
    sections.append("")

    return "\n".join(sections)


def execute(
    project_type: str = "web",
    config: dict = None,
    target: str = "cloud",
    **kwargs,
) -> SkillResult:
    if project_type not in _VALID_PROJECT_TYPES:
        return SkillResult.fail(
            f"Invalid project_type '{project_type}'. Must be one of: {_VALID_PROJECT_TYPES}"
        )

    if target not in _VALID_TARGETS:
        return SkillResult.fail(
            f"Invalid target '{target}'. Must be one of: {_VALID_TARGETS}"
        )

    if config is None:
        config = {}

    generators = {
        "localhost": _generate_localhost,
        "cloud": _generate_cloud,
        "edge": _generate_edge,
    }

    files = generators[target](project_type, config)
    files[".env.example"] = _env_template(config)

    output = _build_output_markdown(project_type, target, config, files)

    file_list = list(files.keys())
    data = {
        "needs_deploy": False,
        "project_type": project_type,
        "target": target,
        "config": config,
        "generated_files": file_list,
        "file_count": len(file_list),
    }

    return SkillResult.ok(output=output, data=data)


def register(registry) -> None:
    registry.register(SkillDef(
        name="deploy_helper",
        description="Generates deployment config files and documentation for web, API, and static projects targeting cloud, edge, or localhost.",
        category="deployment",
        parameters={
            "type": "object",
            "properties": {
                "project_type": {
                    "type": "string",
                    "enum": ["web", "api", "static"],
                    "description": "Type of project to deploy",
                },
                "config": {
                    "type": "object",
                    "description": "Deployment configuration: port, runtime, region, workers, cors_origin",
                },
                "target": {
                    "type": "string",
                    "enum": ["cloud", "edge", "localhost"],
                    "description": "Deployment target environment",
                },
            },
            "required": [],
        },
        handler=execute,
        timeout=120,
    ))
