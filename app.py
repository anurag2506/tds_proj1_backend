from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from typing import List, Dict, Optional
import os
import time
import tempfile
from dotenv import load_dotenv
import asyncio
from aipipe_client import call_aipipe
import base64
import tempfile
from utils import *

# Load environment variables
load_dotenv()

app = FastAPI(title="TDS LLM Deployment", version="1.0.0")

# Get environment variables
STUDENT_SECRET = os.getenv("STUDENT_SECRET")
STUDENT_EMAIL = os.getenv("STUDENT_EMAIL")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_USERNAME = os.getenv("GITHUB_USERNAME")
AIPIPE_API_KEY = os.getenv("AIPIPE_API_KEY")


# Pydantic models for request/response
class Attachment(BaseModel):
    name: str
    url: str


class TaskRequest(BaseModel):
    email: str
    secret: str
    task: str
    round: int
    nonce: str
    brief: str
    checks: List[str]
    evaluation_url: str
    attachments: List[Attachment] = []


# Root endpoint for health check
@app.get("/")
async def root():
    return {
        "message": "TDS LLM Deployment API is running!",
        "student_email": STUDENT_EMAIL,
        "status": "ready",
    }


# Main endpoint that will receive tasks
@app.post("/api-endpoint")
async def receive_task(request: TaskRequest, background_tasks: BackgroundTasks):
    """
    Main endpoint that receives task requests from instructors.
    CRITICAL: Must return HTTP 200 within seconds.
    """

    # Step 1: Verify secret immediately
    if request.secret != STUDENT_SECRET:
        raise HTTPException(status_code=401, detail="Invalid secret")

    print(f"✅ Received valid task: {request.task} (Round {request.round})")

    # Step 2: Add to background processing (we'll implement this next)
    background_tasks.add_task(process_task_background, request.dict())

    # Step 3: Return 200 immediately
    return {
        "status": "accepted",
        "message": "Task received and processing started",
        "task": request.task,
        "round": request.round,
    }


async def process_task_background(task_data):
    token = os.getenv("GITHUB_TOKEN")
    round_number = task_data["round"]
    repo_name = task_data["task"]  # Use the same repo name for both rounds
    username = GITHUB_USERNAME

    if round_number == 2:
        print("🔁 Detected Round 2 (Revision) request!")
        try:
            # Fetch existing code from GitHub
            existing_code = await fetch_github_file(
                repo_name=repo_name,
                filename="index.html",
                token=token,
                branch="main",
                username=username,
            )
            print("✅ Existing index.html fetched from GitHub repo.")

            # Compose the revision prompt
            new_brief = task_data["brief"]
            checks = task_data["checks"]

            revision_prompt = (
                "You are updating a previously deployed static website. "
                "Below is the current code for the website (index.html):\n\n"
                "----- OLD CODE START -----\n"
                f"{existing_code}\n"
                "----- OLD CODE END -----\n\n"
                "Your new instructions are:\n"
                f"{new_brief}\n\n"
                "You must update the code to implement these new requirements "
                "while preserving all existing original features unless a change is requested. "
                "The following code checks will be used to automatically test your solution:\n"
                f"{chr(10).join('- ' + c for c in checks)}\n\n"
                "Return ONLY the complete updated HTML file, starting with <!DOCTYPE html>."
            )
            print("📝 Revision prompt created, sending to LLM...")

            # Call LLM with revision prompt
            revision_response = await call_aipipe(revision_prompt)
            revised_html = revision_response["choices"][0]["message"]["content"]
            print("✅ Received revised HTML from LLM.")

            # Clone the repo (recommended to avoid git history issues)

            with tempfile.TemporaryDirectory() as tempdir:
                clone_repo(repo_name, token, tempdir, username=username)
                # Overwrite index.html with revised content
                filename = os.path.join(tempdir, "index.html")
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(revised_html)
                print(f"✅ Revised index.html saved to {filename}")

                # Optionally overwrite README.md/lic if needed; mostly, just commit index.html
                commit_sha = push_to_github(
                    f"https://github.com/{username}/{repo_name}", token, tempdir
                )
                print(f"✅ Revision pushed. Commit SHA: {commit_sha}")

                # Enable GitHub Pages (should already be enabled, but harmless to re-call)
                enabled = enable_github_pages(repo_name, token, branch="main")
                if enabled:
                    pages_url = f"https://{username}.github.io/{repo_name}/"
                    print(f"🎉 Your revised app should soon be live at {pages_url}")
                else:
                    print("❗Caution: Pages not enabled, check error above.")

                # Notify evaluator
                payload = {
                    "email": task_data["email"],
                    "task": repo_name,
                    "round": round_number,
                    "nonce": task_data["nonce"],
                    "repo_url": f"https://github.com/{username}/{repo_name}",
                    "commit_sha": commit_sha,
                    "pages_url": pages_url,
                }
                print("📦 Notifying evaluator with payload:")
                print(payload)
                print("📨 Sending to:", task_data["evaluation_url"])

                success = await notify_evaluator(task_data["evaluation_url"], payload)
                print(
                    "🎯 Evaluation API notified successfully!"
                    if success
                    else "❌ Failed to notify evaluator after retries."
                )

        except Exception as e:
            print("❌ Round 2 revision error:", e)
            return

    else:
        print("🆕 Detected Round 1 (Initial build) request!")

        print(f"🔄 Processing task for: {task_data['task']}")
        brief = task_data["brief"]
        checks = task_data["checks"]

        # Compose the prompt for AI Pipe
        prompt = (
            f"""You are an expert frontend developer. 
    Given these requirements:\n\n{brief}\n\n"""
            f"""The following checks will be performed by the evaluator: 
    {chr(10).join("- " + c for c in checks)}\n\n"""
            f"""You may be given file attachments, refer to them by the names below: """
            f"""{[a["name"] for a in task_data.get("attachments", [])]}\n\n"""
            f"""Please output a single complete HTML file with embedded CSS and JS as required. 
    The HTML output must pass all checks. Start your output directly with <!DOCTYPE html> (no code fences)."""
        )
        print("🔎 Calling AI Pipe with full prompt to generate app code...")
        response = await call_aipipe(prompt)

        try:
            llm_message = response["choices"][0]["message"]["content"]
            # 1. Create a temp directory for repo files
            with tempfile.TemporaryDirectory() as tempdir:
                # Save index.html
                filename = os.path.join(tempdir, "index.html")
                with open(filename, "w", encoding="utf-8") as f:
                    f.write(llm_message)
                print(f"✅ index.html saved to {filename}")

                # Save README.md and LICENSE
                readme = generate_readme(brief, checks, task_data["task"])
                license_text = generate_mit_license(author=STUDENT_EMAIL or "anonymous")
                with open(
                    os.path.join(tempdir, "README.md"), "w", encoding="utf-8"
                ) as f:
                    f.write(readme)
                print(f"✅ README.md saved")
                with open(os.path.join(tempdir, "LICENSE"), "w", encoding="utf-8") as f:
                    f.write(license_text)
                print(f"✅ LICENSE saved")

                # 🚀 2. Create the repo via GitHub API
                repo_name = task_data["task"]
                token = os.getenv("GITHUB_TOKEN")
                description = brief
                print(f"🚀 Creating GitHub repo: {repo_name}")
                repo_url = create_github_repo(repo_name, token, description)
                print(f"✅ GitHub repo created at: {repo_url}")

                # 🚀 3. Push files to GitHub repo
                print(f"🚀 Pushing files to GitHub repo...")
                try:
                    commit_sha = push_to_github(repo_url, token, tempdir)
                    print(f"✅ Files pushed to repo. Commit SHA: {commit_sha}")
                    enabled = enable_github_pages(repo_name, token, branch="main")
                    if enabled:
                        pages_url = f"https://{GITHUB_USERNAME}.github.io/{repo_name}/"
                        print(f"🎉 Your app should soon be live at {pages_url}")
                    else:
                        print("❗Caution: Pages not enabled, check error above.")
                    payload = {
                        "email": task_data["email"],
                        "task": repo_name,
                        "round": task_data["round"],
                        "nonce": task_data["nonce"],
                        "repo_url": repo_url,
                        "commit_sha": commit_sha,
                        "pages_url": pages_url,
                    }
                    print("📦 Notifying evaluator with payload:")
                    print(payload)
                    print("📨 Sending to:", task_data["evaluation_url"])

                    success = await notify_evaluator(
                        task_data["evaluation_url"], payload
                    )
                    if success:
                        print("🎯 Evaluation API notified successfully!")
                    else:
                        print("❌ Failed to notify evaluator after retries.")

                except Exception as ex:
                    print(f"❌ Git push error: {ex}")
                    return  # Stop here if failed

                # OPTIONAL: Print repo link for easy access
                print(f"🎉 SUCCESS: App deployed at {repo_url}")

            print(
                "📝 LLM output (trimmed):",
                llm_message[:400],
                "..." if len(llm_message) > 400 else "",
            )
        except Exception as e:
            print("LLM response parse error:", e, response)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
