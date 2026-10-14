import urllib.request
import json
import time

url = "https://api.github.com/repos/mcdowellsjohn07/nexglo-ai-wa/actions/runs"
headers = {"User-Agent": "agent"}

for _ in range(12):
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            runs = data.get("workflow_runs", [])
            if runs:
                latest = runs[0]
                status = latest.get("status")
                conclusion = latest.get("conclusion")
                msg = latest.get("head_commit", {}).get("message", "")[:45]
                print(f"Run ID: {latest.get('id')} | Status: {status} | Conclusion: {conclusion} | Commit: {msg}")
                if status == "completed":
                    break
    except Exception as e:
        print("Polling error:", e)
    time.sleep(10)
