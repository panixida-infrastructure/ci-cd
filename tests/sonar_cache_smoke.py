"""Run against a disposable SonarQube instance, rejecting every component download.

Requires Python 3.12+, .NET 10 and Java 21+. Never point this at production:
the test changes the disposable instance's initial admin password and creates a project.
"""

import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server-url", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    args = parser.parse_args()
    server_url = args.server_url.rstrip("/")
    action = Path(__file__).resolve().parents[1] / ".github/actions/sonar-cache"
    config = json.loads((action / "versions.json").read_text())
    for _ in range(300):
        try:
            with urllib.request.urlopen(server_url + "/api/system/status", timeout=5) as response:
                if json.load(response)["status"] == "UP":
                    break
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(2)
    else:
        raise RuntimeError("Disposable SonarQube did not start")

    def post(path, fields, password):
        auth = base64.b64encode(f"admin:{password}".encode()).decode()
        request = urllib.request.Request(server_url + path,
                                         data=urllib.parse.urlencode(fields).encode(),
                                         headers={"Authorization": f"Basic {auth}"})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            detail = error.read().decode().replace(password, "[password]")
            raise RuntimeError(f"Disposable server setup failed: {path}: {detail}") from None

    password = "Cache!42" + secrets.token_hex(20)
    post("/api/users/change_password",
         {"login": "admin", "previousPassword": "admin", "password": password}, "admin")
    post("/api/projects/create", {"project": "shared-cache-smoke", "name": "Shared cache smoke"}, password)
    token = json.loads(post("/api/user_tokens/generate", {"name": "cache-smoke"}, password))["token"]
    blocked = []

    class Proxy(BaseHTTPRequestHandler):
        def log_message(self, format, *arguments):
            pass

        def forward(self):
            path = self.path.split("?")[0]
            if (path in ("/api/plugins/download", "/batch/file") or path.startswith("/static/")
                    or (path == "/api/v2/analysis/engine"
                        and "application/octet-stream" in self.headers.get("Accept", ""))):
                blocked.append(self.path)
                self.send_error(503, "Component downloads are forbidden in this smoke test")
                return
            body = self.rfile.read(int(self.headers.get("Content-Length", 0))) or None
            headers = {key: value for key, value in self.headers.items()
                       if key.lower() not in ("host", "connection", "transfer-encoding")}
            request = urllib.request.Request(server_url + self.path, data=body,
                                             headers=headers, method=self.command)
            try:
                response = urllib.request.urlopen(request, timeout=60)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                content = response.read()
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in ("connection", "transfer-encoding", "content-length"):
                        self.send_header(key, value)
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)

        do_GET = forward
        do_POST = forward

    def run(command, directory):
        # The disposable Community instance analyzes its own main project, not this PR.
        environment = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")}
        result = subprocess.run(command, cwd=directory, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, env=environment)
        print(result.stdout.replace(token, "[token]"))
        if result.returncode:
            raise RuntimeError(f"Smoke command failed: {command[0]}")

    with ThreadingHTTPServer(("127.0.0.1", 0), Proxy) as proxy, tempfile.TemporaryDirectory() as temporary:
        threading.Thread(target=proxy.serve_forever, daemon=True).start()
        temporary = Path(temporary)
        sonar_home = temporary / ".sonar"
        os.environ["SONAR_USER_HOME"] = str(sonar_home)
        run(["python3", str(action / "cache.py"), "restore", "--source", str(args.archive),
             "--destination", str(sonar_home), "--server-version", config["server_version"]], temporary)
        tools = temporary / "tools"
        run(["dotnet", "tool", "install", "dotnet-sonarscanner", "--tool-path", str(tools),
             "--version", config["scanner_version"], "--configfile", str(sonar_home / "nuget.config")], temporary)
        project = temporary / "project"
        run(["dotnet", "new", "classlib", "--framework", "net10.0", "--output", str(project)], temporary)
        (project / "sample.json").write_text('{"test": true}\n')
        (project / "sample.js").write_text('export const answer = 42;\n')
        scanner = str(tools / "dotnet-sonarscanner")
        run([scanner, "begin", "/k:shared-cache-smoke", f"/d:sonar.token={token}",
             f"/d:sonar.host.url=http://127.0.0.1:{proxy.server_port}",
             "/d:sonar.scanner.skipJreProvisioning=true",
             f"/d:sonar.userHome={sonar_home}",
             f"/d:sonar.plugin.cache.directory={sonar_home / 'resources'}"], project)
        run(["dotnet", "build", "--no-restore"], project)
        run([scanner, "end", f"/d:sonar.token={token}"], project)
        proxy.shutdown()
    if blocked:
        raise RuntimeError(f"Unexpected component downloads: {blocked}")
    print("PASS: .NET, JavaScript and JSON analysis completed with zero component downloads")


if __name__ == "__main__":
    main()
