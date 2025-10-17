from datetime import datetime
import httpx
import subprocess
import os
import asyncio
import base64


def clone_repo(repo_name, token, tempdir, username=None):
    if username is None:
        username = os.getenv("GITHUB_USERNAME")
    repo_url = f"https://github.com/{username}/{repo_name}"
    url_with_token = repo_url.replace("https://", f"https://{token}@")
    subprocess.run(["git", "clone", url_with_token, tempdir], check=True)


async def fetch_github_file(repo_name, filename, token, branch="main", username=None):
    if username is None:
        username = os.getenv("GITHUB_USERNAME")
    api_url = f"https://api.github.com/repos/{username}/{repo_name}/contents/{filename}?ref={branch}"
    headers = {"Authorization": f"token {token}"}
    response = httpx.get(api_url, headers=headers)
    if response.status_code == 200:
        content_base64 = response.json()["content"]
        # Remove line breaks for base64 decoding
        content_base64_clean = "".join(content_base64.splitlines())
        return base64.b64decode(content_base64_clean).decode("utf-8")
    else:
        raise Exception(
            f"Cannot fetch {filename} from {repo_name}: {response.status_code}, {response.text}"
        )


async def notify_evaluator(evaluation_url, payload):
    headers = {"Content-Type": "application/json"}
    for attempt in range(5):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    evaluation_url, json=payload, timeout=30, headers=headers
                )
            print("Response status code:", response.status_code)
            print("Response text:", response.text)
            if response.status_code == 200:
                print("✅ Notified evaluation server.")
                return True
            else:
                print(
                    f"❗Evaluator returned status {response.status_code}: {response.text}"
                )
        except Exception as e:
            print(f"❗Notify attempt {attempt + 1} failed: {e}")
        await asyncio.sleep(2**attempt)
    return False


def enable_github_pages(repo_name, token, branch="main"):
    """Enable GitHub Pages via API for the repo's main branch."""
    api_url = (
        f"https://api.github.com/repos/{os.getenv('GITHUB_USERNAME')}/{repo_name}/pages"
    )
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {"source": {"branch": branch, "path": "/"}}
    print(f"🚀 Enabling GitHub Pages at {api_url}")
    response = httpx.post(api_url, headers=headers, json=data)
    if response.status_code in [201, 204, 409]:  # 409 if already enabled
        print("✅ GitHub Pages enabled or already active.")
        return True
    print("❌ Failed to enable GitHub Pages:", response.status_code, response.text)
    return False


def create_github_repo(repo_name, token, description=""):
    """Create a new public GitHub repository via API."""
    api_url = "https://api.github.com/user/repos"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    data = {
        "name": repo_name,
        "description": description,
        "private": False,
        "auto_init": False,
    }
    response = httpx.post(api_url, headers=headers, json=data)
    if response.status_code in [201, 422]:  # 422 if already exists
        print("✅ Repo creation response:", response.status_code)
        return f"https://github.com/{os.getenv('GITHUB_USERNAME')}/{repo_name}"
    raise Exception(f"Failed to create repo: {response.text}")


def push_to_github(repo_url, gh_token, folder):
    """Commit and push files from folder to GitHub repo.
    Works for both new git init or freshly cloned repo.
    """
    # Initialize git repo if missing
    if not os.path.isdir(os.path.join(folder, ".git")):
        subprocess.run(["git", "init"], cwd=folder, check=True)

    # Always set user info
    subprocess.run(
        ["git", "config", "user.email", "llm-bot@aiexample.com"], cwd=folder, check=True
    )
    subprocess.run(["git", "config", "user.name", "llm-bot"], cwd=folder, check=True)

    # Stage changes
    subprocess.run(["git", "add", "."], cwd=folder, check=True)

    # Only commit if there are changes
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=folder,
        capture_output=True,
        text=True,
    )
    if status.stdout.strip():
        subprocess.run(
            ["git", "commit", "-m", "Automated commit"], cwd=folder, check=True
        )
    else:
        print("ℹ️ No changes to commit; skipping git commit.")

    repo_url_with_token = repo_url.replace("https://", f"https://{gh_token}@")

    # Try to set-url; if it fails, add remote origin
    try:
        subprocess.run(
            ["git", "remote", "set-url", "origin", repo_url_with_token],
            cwd=folder,
            check=True,
        )
    except subprocess.CalledProcessError:
        subprocess.run(
            ["git", "remote", "add", "origin", repo_url_with_token],
            cwd=folder,
            check=True,
        )

    subprocess.run(["git", "branch", "-M", "main"], cwd=folder, check=True)
    subprocess.run(
        ["git", "push", "-u", "origin", "main", "--force"], cwd=folder, check=True
    )

    # Get latest commit SHA
    sha = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=folder)
        .decode()
        .strip()
    )
    return sha


def generate_readme(brief, checks, task_id):
    return f"""# {task_id}

## Overview
This project is a single-page app generated for the brief:

> {brief}

## Checks Implemented
{chr(10).join("- " + c for c in checks)}

## Usage
Open `index.html` in your browser. All required logic, CSS and JS are included in this file.

## License
MIT
"""


def generate_mit_license(author):
    year = datetime.now().year
    return f"""MIT License

Copyright (c) {year} {author}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
