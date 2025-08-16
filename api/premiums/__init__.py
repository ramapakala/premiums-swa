import json, os, sys, platform
import azure.functions as func

def main(req: func.HttpRequest) -> func.HttpResponse:
    data = {
        "ok": True,
        "python": sys.version,
        "platform": platform.platform(),
        "func_dir": os.path.dirname(__file__),
        "files_in_func_dir": sorted(os.listdir(os.path.dirname(__file__))),
        "env": {k: os.environ.get(k, "") for k in [
            "FUNCTIONS_WORKER_RUNTIME", "AzureWebJobsFeatureFlags",
            "WEBSITE_SITE_NAME", "SYMBOLS"
        ]}
    }
    return func.HttpResponse(json.dumps(data), mimetype="application/json", status_code=200)
