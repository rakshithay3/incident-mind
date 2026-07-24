import os
import subprocess
import shutil
import stat

SERVICES_DIR = "services"
HISTORY_DIR = "code-agent-history"

def run_cmd(cmd, cwd=None):
    res = subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, shell=True)
    return res

def rmtree_readonly(path):
    if not os.path.exists(path):
        return
    def remove_readonly(func, p, excinfo):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=remove_readonly)

def setup_repos():
    # Determine all services under services/
    if not os.path.exists(SERVICES_DIR):
        print(f"Error: {SERVICES_DIR} directory not found.")
        return

    services = [d for d in os.listdir(SERVICES_DIR) if os.path.isdir(os.path.join(SERVICES_DIR, d))]
    
    # Exclude frontend/api-gateway if they don't have code changes needed by Code Agent
    # but we can process all directories in services/ to be thorough
    print(f"Found services: {services}")
    os.makedirs(HISTORY_DIR, exist_ok=True)
    
    for srv in services:
        srv_path = os.path.join(SERVICES_DIR, srv)
        target_path = os.path.join(HISTORY_DIR, srv)
        branch_name = f"{srv}-history"
        
        print(f"\n--- Setting up Git history for {srv} ---")
        
        # 1. Split monorepo path history into a branch
        # Delete branch first if it already exists to rebuild it cleanly
        run_cmd(f"git branch -D {branch_name}")
        
        print(f"Running git subtree split for {srv_path} to branch {branch_name}...")
        res = run_cmd(f"git subtree split --prefix={SERVICES_DIR}/{srv} -b {branch_name}")
        if res.returncode != 0:
            print(f"Failed to split subtree history for {srv}. Error:\n{res.stderr.strip()}")
            continue
            
        # 2. Extract branch history into separate code-agent-history/<service_name> folder
        if os.path.exists(target_path):
            print(f"Cleaning up existing history directory: {target_path}...")
            rmtree_readonly(target_path)
            
        print(f"Cloning local split branch {branch_name} into {target_path}...")
        res = run_cmd(f"git clone --branch {branch_name} --local . {target_path}")
        if res.returncode == 0:
            print(f"Successfully created isolated repository with real history for {srv}!")
            # Clean up the local temporary branch
            run_cmd(f"git branch -D {branch_name}")
        else:
            print(f"Failed to clone history branch for {srv}. Error:\n{res.stderr.strip()}")

if __name__ == "__main__":
    setup_repos()
