def build_argv(job, session_id=None, windows=False):
    args = ["exec", "--ignore-user-config", "--json"]
    if job["auth"] == "subscription":
        args += ["-c", 'forced_login_method="chatgpt"']
    if windows:
        args += ["-c", "features.prefer_mxc=true", "-c", 'windows.sandbox="elevated"']
    if job["permissions"] == "full":
        args += ["--dangerously-bypass-approvals-and-sandbox"]
    else:
        args += ["-s", {"read-only": "read-only", "edit": "workspace-write"}[job["permissions"]]]
    if job["model"]["name"]:
        args += ["--model", job["model"]["name"]]
    if job["model"]["effort"]:
        args += ["-c", 'model_reasoning_effort=' + '"' + job["model"]["effort"] + '"']
    args += ["--output-schema", job["schema_path"]]
    if session_id:
        args += ["resume", session_id]
    args += ["-"]
    return args
