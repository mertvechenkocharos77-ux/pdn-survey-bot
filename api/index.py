import os
import json
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
    return await asyncpg.connect(DATABASE_URL)


# ========== ЛОГИКА РАСЧЁТА БАЛЛОВ ==========
def calculate_scores(answers: dict) -> tuple:
    """
    Принимает словарь с ответами q1..q18.
    Возвращает: integration_score, identity_score, result_text
    """
    def get_int(q_name):
        val = answers.get(q_name)
        try:
            return int(val)
        except:
            return 3  # по умолчанию, если ответа нет
    
    # Часть А: интеграция (q1 - q7)
    integration_answers = [get_int(f"q{i}") for i in range(1, 8)]
    integration_avg = sum(integration_answers) / 7
    
    # Часть Б: идентичность (q8 - q14)
    identity_answers = [get_int(f"q{i}") for i in range(8, 15)]
    identity_avg = sum(identity_answers) / 7
    
    # Округляем до целых для сохранения в БД (от 10 до 50)
    integration_score = round(integration_avg * 10)
    identity_score = round(identity_avg * 10)
    
    def get_level(avg):
        if avg <= 2.4:
            return "низкий"
        elif avg <= 3.9:
            return "средний"
        else:
            return "высокий"
    
    integration_level = get_level(integration_avg)
    identity_level = get_level(identity_avg)
    
    # Проверяем гармоничность
    diff = abs(integration_avg - identity_avg)
    if diff <= 0.5:
        harmony = "гармоничное развитие"
    elif integration_avg > identity_avg:
        harmony = "дисбаланс в сторону интеграции"
    else:
        harmony = "дисбаланс в сторону идентичности"
    
    # Формируем текст результата
    result_text = f"""По результатам анкетирования:

📊 **Интеграция в российское общество**: {integration_level} уровень ({integration_avg:.1f} из 5)
👨‍👩‍👧 **Сохранение национальной идентичности**: {identity_level} уровень ({identity_avg:.1f} из 5)
⚖️ **Характер развития**: {harmony}

"""
    
    # Добавляем рекомендации
    if integration_level == "низкий" and identity_level == "низкий":
        result_text += "Рекомендация: обратитесь за поддержкой к классному руководителю, психологу или инспектору ПДН. Участие в групповых занятиях поможет лучше понять себя и окружающих."
    elif integration_level == "высокий" and identity_level == "высокий":
        result_text += "Рекомендация: продолжайте участвовать в школьных событиях, делитесь своим опытом со сверстниками. У вас гармоничная позиция!"
    elif integration_level == "высокий":
        result_text += "Рекомендация: больше общайтесь с семьёй на родном языке, участвуйте в семейных праздниках. Ваши корни — это ваша сила."
    elif identity_level == "высокий":
        result_text += "Рекомендация: активнее включайтесь в школьную жизнь, изучайте историю и традиции России. Это поможет лучше понимать одноклассников."
    elif integration_level == "низкий" or identity_level == "низкий":
        result_text += "Рекомендация: обсудите результаты с педагогом-психологом. Вам может помочь участие в программе «На перекрёстке культур: обретая себя»."
    else:
        result_text += "Рекомендация: продолжайте участвовать в мероприятиях программы, задавайте вопросы, делитесь своими мыслями с семьёй и учителями."
    
    return integration_score, identity_score, result_text


# ========== ВЕБХУК ДЛЯ ЯНДЕКС.ФОРМЫ ==========
@app.post("/api/webhook")
async def yandex_webhook(request: Request):
    try:
        data = await request.json()
    except:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    participant_id = data.get("participant_id")
    if not participant_id:
        raise HTTPException(status_code=400, detail="participant_id is required")
    
    # Собираем ответы на вопросы q1...q18
    answers = {}
    for i in range(1, 19):
        q_key = f"q{i}"
        answers[q_key] = data.get(q_key)
    
    conn = await get_db()
    
    # Проверяем, существует ли участник в таблице participants
    participant = await conn.fetchrow(
        "SELECT participant_id FROM participants WHERE participant_id = $1",
        participant_id
    )
    if not participant:
        await conn.close()
        raise HTTPException(status_code=404, detail="Participant not found")
    
    # Расчёт баллов и текста результата
    integration_score, identity_score, result_text = calculate_scores(answers)
    
    # Сохраняем результат в БД
    await conn.execute("""
        INSERT INTO survey_results (participant_id, answers_json, integration_score, identity_score, result_text)
        VALUES ($1, $2, $3, $4, $5)
    """, participant_id, json.dumps(answers), integration_score, identity_score, result_text)
    
    await conn.close()
    return {"status": "ok"}


# ========== АДМИН-ПАНЕЛЬ ==========
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


@app.get("/")
async def root():
    return {"message": "Сервер работает. Используйте /admin или /api/webhook"}


# ========== ДЛЯ ЛОКАЛЬНОГО ЗАПУСКА (НЕ ИСПОЛЬЗУЕТСЯ НА VERCEL) ==========
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
