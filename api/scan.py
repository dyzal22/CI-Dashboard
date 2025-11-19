from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import requests
from bs4 import BeautifulSoup
import time
import uuid
import json
import os

# PDF
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

app = FastAPI()
templates = Jinja2Templates(directory="templates")

SAFE_PAYLOADS = [
    "|echo POC_TEST",
    "|whoami",
    "|uname -a",
    "|sleep 2"
]


# ==================================================
# AUTH HEADER BUILDER
# ==================================================
def build_headers(auth_type, bearer, cookie, custom_headers):
    headers = {"User-Agent": "CI-Dashboard/1.0"}

    if auth_type == "bearer" and bearer:
        headers["Authorization"] = f"Bearer {bearer}"

    if cookie:
        headers["Cookie"] = cookie

    if custom_headers:
        for line in custom_headers.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                headers[key.strip()] = val.strip()

    return headers


# ==================================================
# PARAM DISCOVERY
# ==================================================
def discover_parameters(url):
    try:
        r = requests.get(url, timeout=5)
        soup = BeautifulSoup(r.text, "lxml")

        params = []

        for form in soup.find_all("form"):
            for inp in form.find_all("input"):
                if inp.get("name"):
                    params.append(inp.get("name"))

        return list(set(params)) if params else []
    except:
        return []


# ==================================================
# PAYLOAD TESTER
# ==================================================
def test_payload(url, param, payload, headers, method="get"):
    try:
        start = time.time()

        if method == "post":
            res = requests.post(url, data={param: payload},
                                headers=headers, timeout=5)
        else:
            res = requests.get(url, params={param: payload},
                               headers=headers, timeout=5)

        delta = time.time() - start

        return {
            "payload": payload,
            "status": res.status_code,
            "response_time": round(delta, 2),
            "body_snippet": res.text[:200],
            "headers": dict(res.headers)
        }

    except Exception as e:
        return {"payload": payload, "error": str(e)}


# ==================================================
# ROOT PAGE
# ==================================================
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ==================================================
# MAIN SCAN ENDPOINT
# ==================================================
@app.post("/scan", response_class=HTMLResponse)
async def scan(
    request: Request,
    url: str = Form(...),
    param: str = Form("auto"),
    method: str = Form("get"),
    auth_type: str = Form("none"),
    bearer: str = Form(""),
    cookie: str = Form(""),
    headers: str = Form("")
):

    hdrs = build_headers(auth_type, bearer, cookie, headers)

    if param == "auto":
        params = discover_parameters(url)
        if not params:
            return templates.TemplateResponse("error.html", {
                "request": request,
                "msg": "Tidak ada parameter ditemukan secara otomatis."
            })
    else:
        params = [param]

    result_data = []

    for p in params:
        results = []
        for pl in SAFE_PAYLOADS:
            r = test_payload(url, p, pl, hdrs, method)
            results.append(r)

        result_data.append({
            "param": p,
            "tests": results
        })

    return templates.TemplateResponse("result.html", {
        "request": request,
        "url": url,
        "method": method,
        "results": result_data
    })


# ==================================================
# PDF EXPORT ENDPOINT
# ==================================================
@app.post("/export_pdf")
async def export_pdf(url: str = Form(...), data: str = Form(...)):
    file_id = str(uuid.uuid4())
    pdf_path = f"/tmp/report_{file_id}.pdf"

    decoded = json.loads(data)

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(pdf_path)
    flow = []

    flow.append(Paragraph("<b>Command Injection Report</b>", styles["Title"]))
    flow.append(Spacer(1, 20))
    flow.append(Paragraph(f"<b>Target URL:</b> {url}", styles["Normal"]))
    flow.append(Spacer(1, 10))

    for r in decoded:
        flow.append(Paragraph(f"<b>Parameter:</b> {r['param']}", styles["Heading2"]))

        for t in r["tests"]:
            flow.append(Paragraph(f"<b>Payload:</b> {t['payload']}", styles["Normal"]))

            if "status" in t:
                flow.append(Paragraph(f"Status: {t['status']}", styles["Normal"]))
                flow.append(Paragraph(f"Response Time: {t.get('response_time', '-')}", styles["Normal"]))
                flow.append(Paragraph(f"Snippet:<br/>{t['body_snippet']}", styles["Normal"]))
            else:
                flow.append(Paragraph(f"Error: {t['error']}", styles["Normal"]))

            flow.append(Spacer(1, 10))

    doc.build(flow)

    return FileResponse(pdf_path, filename="CI_Report.pdf")
