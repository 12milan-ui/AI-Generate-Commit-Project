
#!/usr/bin/env python3
"""
AI project generator script

- Calls the OpenAI API to request a JSON structure describing files to write.
- Writes files into the repository.
- Prints a commit message block (used by the workflow step if needed).

IMPORTANT:
- Set OPENAI_API_KEY in environment (GitHub Actions secrets).
- The model name used can be changed below if you prefer a different model.
"""

import os
import sys
import json
import re
import base64
import subprocess
from pathlib import Path

# Try to support both the older "openai" package and the newer "openai.OpenAI" SDK.
sdk_new = False
try:
    from openai import OpenAI
    sdk_new = True
except Exception:
    try:
        import openai
    except Exception:
        print("Please ensure the 'openai' Python package is installed (pip install openai).")
        sys.exit(1)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    print("OPENAI_API_KEY not set in environment. Set it in repo secrets.")
    sys.exit(1)

PROJECT_DESCRIPTION = os.getenv("PROJECT_DESCRIPTION", "").strip()
LANGUAGE = os.getenv("LANGUAGE", "javascript").strip()

system_prompt = f"""
You are a code generator. The user asked: {PROJECT_DESCRIPTION!s}

Produce a single JSON object only (no extra text). The JSON format must be:
{{
  "files": {{
     "path/to/file.ext": "file content as a string (use \\n for newlines)",
     ...
  }},
  "commit_message": "A one-line commit message describing the generated project"
}}

Rules:
- Return only valid JSON. Do not wrap JSON in markdown.
- If a file must be binary (images, etc.) return an object with keys: content_base64 and binary: true, e.g.:
  "assets/logo.png": {{"content_base64": "...base64...", "binary": true}}
- Keep file sizes reasonable. If many files are required, produce a minimal working full-stack project (frontend + backend + README + basic tests).
- Do NOT include secrets, private keys, or TODOs that require secret values.
- Use common conventions for the chosen LANGUAGE ({LANGUAGE}).
- Include a clear README.md and basic start/test commands in package config or requirements and mention them in README content.
"""

user_prompt = f"Generate a minimal, working full-stack project (frontend + backend) for: {PROJECT_DESCRIPTION!s}\nLanguage/stack preference: {LANGUAGE}"

messages = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": user_prompt}
]

print("Calling OpenAI to generate code...")

resp_text = None
try:
    if sdk_new:
        client = OpenAI(api_key=OPENAI_API_KEY)
        completion = client.chat.completions.create(
            model="gpt-4o-mini",  # change model if needed
            messages=messages,
            temperature=0.2,
            max_tokens=3000,
        )
        resp_text = completion.choices[0].message["content"]
    else:
        openai.api_key = OPENAI_API_KEY
        completion = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=messages,
            temperature=0.2,
            max_tokens=3000,
        )
        resp_text = completion.choices[0].message["content"]
except Exception as e:
    print("OpenAI API call failed:", str(e))
    sys.exit(1)

if not resp_text:
    print("No response from model.")
    sys.exit(1)

def extract_json(text):
    start = text.find('{')
    end = text.rfind('}')
    if start == -1 or end == -1:
        return None
    candidate = text[start:end+1]
    # Remove common comment patterns and trailing commas, best-effort.
    try:
        return json.loads(candidate)
    except Exception:
        cleaned = re.sub(r"//.*?$", "", candidate, flags=re.MULTILINE)
        cleaned = re.sub(r"/\*[\s\S]*?\*/", "", cleaned)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        try:
            return json.loads(cleaned)
        except Exception:
            return None

parsed = extract_json(resp_text)
if not parsed:
    print("Failed to parse JSON from model response. Raw response below for debugging:")
    print(resp_text)
    sys.exit(1)

files = parsed.get("files", {})
commit_message = parsed.get("commit_message", f"AI-generated: {PROJECT_DESCRIPTION}")[:200]

if not isinstance(files, dict) or len(files) == 0:
    print("Model returned no files. Aborting.")
    sys.exit(1)

print(f"Writing {len(files)} file(s) to repo...")

for path, content in files.items():
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, dict) and content.get("binary", False):
        b64 = content.get("content_base64", "")
        if not b64:
            print(f"Binary file {path} missing base64 content. Skipping.")
            continue
        raw = base64.b64decode(b64)
        target.write_bytes(raw)
    else:
        if not isinstance(content, str):
            content = json.dumps(content, indent=2)
        # Convert escaped newlines to real newlines if necessary
        if "\\n" in content and ("\n" not in content):
            try:
                content = content.encode("utf-8").decode("unicode_escape")
            except Exception:
                content = content.replace("\\n", "\n")
        target.write_text(content, encoding="utf-8")

print("Files written.")

# Optionally run safe install/test steps if present (best-effort and non-destructive)
safe_test_commands = []
if Path("package.json").exists():
    safe_test_commands.append(["npm", "install", "--no-audit", "--no-fund"])
    safe_test_commands.append(["npm", "test", "--silent"])
elif Path("requirements.txt").exists():
    safe_test_commands.append([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
    if Path("tests").exists():
        safe_test_commands.append([sys.executable, "-m", "pytest", "-q"])

for cmd in safe_test_commands:
    try:
        print(f"Running safe command: {' '.join(cmd)}")
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"Command succeeded: {' '.join(cmd)}")
    except subprocess.CalledProcessError as e:
        print(f"Command failed (continuing): {' '.join(cmd)}")
        print("stdout:", e.stdout.decode("utf-8", errors="ignore"))
        print("stderr:", e.stderr.decode("utf-8", errors="ignore"))

# Print commit message for the workflow logs
print("COMMIT_MESSAGE_START")
print(commit_message)
print("COMMIT_MESSAGE_END")

print("Generation complete.")
