#!/usr/bin/env python3
"""Interactive test utility to verify your NVIDIA NIM API Key.

Usage:
    python scripts/test_nvidia_key.py
    python scripts/test_nvidia_key.py nvapi-your-key-here
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def main():
    api_key = sys.argv[1] if len(sys.argv) > 1 else os.getenv("NVIDIA_API_KEY", "").strip()

    if not api_key or api_key.startswith("nvapi-XXXX") or api_key == "change-me":
        print("\n========================================================")
        print(" [NVIDIA NIM KEY SETUP]")
        print("========================================================")
        print("To get your free NVIDIA API Key:")
        print("1. Visit https://build.nvidia.com")
        print("2. Sign in or create a free NVIDIA account (1,000 free requests)")
        print("3. Open any model (e.g. 'nvidia/nemotron-3.5-lightning')")
        print("4. Click 'Get API Key' and copy the key (starts with 'nvapi-')")
        print("========================================================")
        api_key = input("\nEnter your NVIDIA API key (or press Enter to cancel): ").strip()
        if not api_key:
            print("Cancelled.")
            sys.exit(1)

    print(f"\n[+] Testing NVIDIA NIM Key: {api_key[:10]}...{api_key[-4:]}")
    model = os.getenv("NIM_MODEL", "nvidia/nemotron-3.5-lightning")
    base_url = os.getenv("NIM_BASE_URL", "https://integrate.api.nvidia.com/v1")

    try:
        from openai import OpenAI
        client = OpenAI(base_url=base_url, api_key=api_key, timeout=25.0)

        start_time = time.time()
        print(f"[+] Connecting to {base_url} with model '{model}'...")
        resp = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are NexgloTV AI Assistant in Freetown, Sierra Leone."},
                {"role": "user", "content": "Respond with 'NVIDIA NEMOTRON ONLINE' and your model name."},
            ],
            max_tokens=60,
            temperature=0.2,
        )
        latency = round((time.time() - start_time) * 1000, 1)
        content = resp.choices[0].message.content.strip()

        print("\n========================================================")
        print(" SUCCESS! NVIDIA NIM KEY IS ACTIVE AND WORKING")
        print("========================================================")
        print(f"Latency:   {latency}ms")
        print(f"Model:     {model}")
        print(f"Response:  {content}")
        print("========================================================")
        print("\nAdd these variables to your BotKeep Environment Variables:")
        print("--------------------------------------------------------")
        print("LLM_PROVIDER=nvidia")
        print(f"NVIDIA_API_KEY={api_key}")
        print(f"NIM_MODEL={model}")
        print("--------------------------------------------------------")

    except Exception as exc:
        print("\n[!] Connection failed:")
        print(f"Error: {exc}")
        print("\nTroubleshooting:")
        print("- Verify that your key starts with 'nvapi-'")
        print("- Check that your account at build.nvidia.com is active")
        sys.exit(1)


if __name__ == "__main__":
    main()
