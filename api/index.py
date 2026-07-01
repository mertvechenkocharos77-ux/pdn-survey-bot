import os
import json
import secrets
import asyncpg
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse

app = FastAPI()
security = HTTPBasic()

DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

async def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured")
    return await asyncpg.connect(DATABASE_URL)

def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    ok_user = secrets.compare_digest(credentials.username, ADMIN_USERNAME)
    ok_pass = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True

@app.get("/")
async def root():
    return {"message":"Server OK"}

@app.get("/test-db")
async def test_db():
    import traceback
    try:
        conn = await get_db()
        val = await conn.fetchval("SELECT current_user")
        await conn.close()
        return {
            "status":"Database connection OK",
            "current_user": val
        }
    except Exception as e:
        return {
            "status":"Database connection FAILED",
            "error":str(e),
            "trace":traceback.format_exc()
        }

@app.get("/debug-db")
async def debug_db():
    url = os.getenv("DATABASE_URL","")
    if "@" not in url:
        return {"configured":False}
    left,right=url.split("@",1)
    user=left.split("://",1)[1].split(":",1)[0]
    host=right.split("/",1)[0]
    return {"user":user,"host":host}

@app.get("/admin", response_class=HTMLResponse)
async def admin(auth: bool = Depends(verify_admin)):
    conn = await get_db()
    rows = await conn.fetch("""
        SELECT r.participant_id,
               r.integration_score,
               r.identity_score,
               r.result_text,
               r.submitted_at,
               p.class
        FROM survey_results r
        LEFT JOIN participants p
          ON p.participant_id=r.participant_id
        WHERE r.is_active=TRUE
        ORDER BY r.submitted_at DESC
    """)
    await conn.close()

    html="""<html><head><meta charset="utf-8">
    <style>
    table{border-collapse:collapse;width:100%%}
    td,th{border:1px solid #ccc;padding:6px}
    </style></head><body>
    <h2>Результаты</h2>
    <table>
    <tr><th>ID</th><th>Класс</th><th>Интеграция</th><th>Идентичность</th><th>Дата</th><th>Результат</th></tr>
    """
    for row in rows:
        html += f"<tr><td>{row['participant_id']}</td><td>{row['class'] or ''}</td><td>{row['integration_score']}</td><td>{row['identity_score']}</td><td>{row['submitted_at']}</td><td>{row['result_text'] or ''}</td></tr>"
    html += "</table></body></html>"
    return html
