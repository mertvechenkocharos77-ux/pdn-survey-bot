import os
import json
import asyncpg
from datetime import datetime
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from typing import Dict, Any, Optional
import uvicorn

app = FastAPI()
security = HTTPBasic()

# Переменные окружения (будут заданы на Render)
DATABASE_URL = os.getenv("DATABASE_URL")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin")

# Подключение к БД
async def get_db():
    conn = await asyncpg.connect(DATABASE_URL)
    return conn

# ---- Вебхук для Яндекс.Формы ----
class WebhookData(BaseModel):
    participant_id: str
    phone: Optional[str] = None
    name: Optional[str] = None
    answers: Dict[str, Any]

@app.post("/api/webhook")
async def yandex_webhook(request: Request):
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    participant_id = data.get("participant_id")
    if not participant_id:
        raise HTTPException(status_code=400, detail="participant_id is required")
    
    conn = await get_db()
    participant = await conn.fetchrow(
        "SELECT participant_id FROM participants WHERE participant_id = $1",
        participant_id
    )
    if not participant:
        await conn.close()
        raise HTTPException(status_code=404, detail="Participant not found")
    
    # Заглушка для расчёта баллов (потом замените на свою логику)
    integration_score = 0
    identity_score = 0
    result_text = "Спасибо за участие! Ваши данные сохранены."
    
    await conn.execute("""
        INSERT INTO survey_results (participant_id, answers_json, integration_score, identity_score, result_text)
        VALUES ($1, $2, $3, $4, $5)
    """, participant_id, json.dumps(data.get("answers", {})), integration_score, identity_score, result_text)
    
    await conn.close()
    return {"status": "ok"}

# ---- Админ-панель ----
def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != ADMIN_USERNAME or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(auth: bool = Depends(verify_admin)):
    conn = await get_db()
    rows = await conn.fetch("""
        SELECT r.*, p.full_name, p.class, p.phone
        FROM survey_results r
        LEFT JOIN participants p ON r.participant_id = p.participant_id
        WHERE r.is_active = TRUE
        ORDER BY r.submitted_at DESC
    """)
    await conn.close()
    
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Админ-панель анкетирования</title>
        <meta charset="utf-8">
        <style>
            body { font-family: sans-serif; margin: 20px; }
            table { border-collapse: collapse; width: 100%; }
            th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
            th { background-color: #f2f2f2; }
            .search { margin-bottom: 20px; }
        </style>
    </head>
    <body>
        <h1>Результаты анкетирования</h1>
        <div class="search">
            <input type="text" id="searchInput" placeholder="Поиск по ID, имени, телефону..." onkeyup="filterTable()">
        </div>
        <table id="dataTable">
            <thead>
                <tr><th>ID участника</th><th>ФИО</th><th>Класс</th><th>Телефон</th><th>Балл интеграции</th><th>Балл идентичности</th><th>Дата</th><th>Рекомендация</th></tr>
            </thead>
            <tbody>
    """
    for row in rows:
        html += f"""
            <tr>
                <td>{row['participant_id']}</td>
                <td>{row.get('full_name', '')}</td>
                <td>{row.get('class', '')}</td>
                <td>{row.get('phone', '')}</td>
                <td>{row['integration_score']}</td>
                <td>{row['identity_score']}</td>
                <td>{row['submitted_at']}</td>
                <td>{row.get('result_text', '')}</td>
            </tr>
        """
    html += """
            </tbody>
        </table>
        <script>
            function filterTable() {
                const input = document.getElementById('searchInput');
                const filter = input.value.toLowerCase();
                const table = document.getElementById('dataTable');
                const tr = table.getElementsByTagName('tr');
                for (let i = 1; i < tr.length; i++) {
                    let tds = tr[i].getElementsByTagName('td');
                    let visible = false;
                    for (let j = 0; j < tds.length; j++) {
                        if (tds[j] && tds[j].innerText.toLowerCase().indexOf(filter) > -1) {
                            visible = true;
                            break;
                        }
                    }
                    tr[i].style.display = visible ? '' : 'none';
                }
            }
        </script>
    </body>
    </html>
    """
    return html

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
