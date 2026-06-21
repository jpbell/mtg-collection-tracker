#!/usr/bin/env python3
import sys
import subprocess
import requests

def get_latest_release():
    import app
    with app.app.app_context():
        # Get latest release note sorted by id descending
        latest = app.ReleaseNote.query.order_by(app.ReleaseNote.id.desc()).first()
        if latest:
            return latest.version, latest.description
    return None, None

def run_git_command(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Git command failed: {' '.join(args)}")
        print(f"Error output: {e.stderr.strip()}")
        return None

def get_github_token_from_git():
    try:
        url = run_git_command(["git", "remote", "get-url", "origin"])
        if url and "@" in url:
            part = url.split("://")[1].split("@")[0]
            if ":" in part:
                return part.split(":")[0]
            return part
    except Exception:
        pass
    return None

def main():
    version, description = get_latest_release()
    if not version:
        print("No release notes found in the database.")
        sys.exit(1)
        
    tag_name = f"v{version}"
    print(f"Latest database version: {version}")
    print(f"Description: {description}")
    
    # 1. Check if tag already exists locally
    existing_tags = run_git_command(["git", "tag"])
    if existing_tags is not None and tag_name in existing_tags.splitlines():
        print(f"Git tag '{tag_name}' already exists locally.")
    else:
        # Create tag locally
        print(f"Creating Git tag '{tag_name}'...")
        if run_git_command(["git", "tag", "-a", tag_name, "-m", description]) is None:
            sys.exit(1)
            
    # 2. Push tag to origin
    print(f"Pushing tag '{tag_name}' to GitHub...")
    if run_git_command(["git", "push", "origin", tag_name]) is None:
        sys.exit(1)
        
    # 3. Create GitHub Release via API
    owner = "jpbell"
    repo = "mtg-collection-tracker"
    
    # Try to find token
    import os
    token = os.environ.get("GITHUB_TOKEN") or get_github_token_from_git()
    if not token:
        print("Warning: Could not detect GitHub Personal Access Token from environment or Git remote URL.")
        print("Please set GITHUB_TOKEN environment variable to complete release generation.")
        sys.exit(1)
        
    url = f"https://api.github.com/repos/{owner}/{repo}/releases"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MTGTracker-Release-Script/1.0"
    }
    payload = {
        "tag_name": tag_name,
        "target_commitish": "main",
        "name": tag_name,
        "body": description,
        "draft": False,
        "prerelease": False
    }
    
    print(f"Creating GitHub Release for '{tag_name}'...")
    res = requests.post(url, headers=headers, json=payload)
    if res.status_code == 201:
        release_data = res.json()
        print(f"SUCCESS! GitHub release created successfully.")
        print(f"Release URL: {release_data.get('html_url')}")
    elif res.status_code == 422:
        print("Release/Tag already exists on GitHub (API returned 422).")
    else:
        print(f"Failed to create GitHub release. Status code: {res.status_code}")
        print(res.text)

if __name__ == '__main__':
    main()
