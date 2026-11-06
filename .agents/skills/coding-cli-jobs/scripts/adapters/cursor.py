def build_argv(job, session_id=None, windows=False):
    if job["model"]["effort"] is not None:
        raise ValueError("Cursor effort is unsupported; omit it explicitly")
    args = ["-p", "--output-format", "stream-json", "--trust"]
    if job["permissions"] == "read-only":
        args += ["--mode", "ask"]
    else:
        args += ["--force", "--sandbox", "disabled" if job["permissions"] == "full" else "enabled"]
    if job["model"]["name"]:
        args += ["--model", job["model"]["name"]]
    if session_id:
        args += ["--resume", session_id]
    return args
