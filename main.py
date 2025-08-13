# Slack Shared Todo Reminder - Backend Server (Python/FastAPI)
# ==========================================================
#
# This file is the core API server using Python and FastAPI.
# FastAPI provides high performance through asynchronous processing and automatically generates API documentation (Swagger UI).
#
# --- How to run ---
# 1. Install Python 3.8+
# 2. Create and activate virtual environment:
#    uv venv
#    uv venv --python 3.12
#    source venv/bin/activate  # macOS/Linux
#    .\venv\Scripts\activate  # Windows
# 3. Install required libraries:
#    uv pip install -r requirements.txt
# 4. Create '.env' file and fill in the database information below.
#    DB_USER=your_postgres_user
#    DB_PASSWORD=your_postgres_password
#    DB_HOST=localhost
#    DB_PORT=5432
#    DB_NAME=slack_todo_db
#    JWT_SECRET=your_super_secret_key_for_jwt
#    ALGORITHM=HS256
#    ACCESS_TOKEN_EXPIRE_MINUTES=30
# 5. Run uvicorn server in terminal:
#    uvicorn main:app --reload  (if main.py is saved)
# 6. Access http://127.0.0.1:8000/docs to view API documentation and test.
#
# main.py
import os
from dotenv import load_dotenv
import asyncpg
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import List, Optional
import jwt
from passlib.context import CryptContext
from datetime import datetime, timedelta, timezone
from fastapi.middleware.cors import CORSMiddleware
import json

# --- 1. Setup and initialization ---
load_dotenv()

def _require_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None or value == "":
        raise RuntimeError(f"Missing env var: {name}")
    return value

# Load environment variables
DATABASE_URL = (
    f"postgresql://{_require_env('DB_USER')}:{_require_env('DB_PASSWORD')}"
    f"@{_require_env('DB_HOST')}:{_require_env('DB_PORT')}/{_require_env('DB_NAME')}"
)
JWT_SECRET = _require_env('JWT_SECRET')
ALGORITHM = os.getenv('ALGORITHM', 'HS256')
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv('ACCESS_TOKEN_EXPIRE_MINUTES', '30'))

# Create FastAPI app instance
app = FastAPI(title="Slack Shared Todo Reminder API")

# CORS configuration (origins managed via environment variable)
origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Password hashing setup
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# OAuth2 setup
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/token")

# Database connection pool
db_pool = None

# --- 2. Event handlers (app startup/shutdown) ---
@app.on_event("startup")
async def startup():
    global db_pool
    # Create database connection pool when app starts
    async def _init_connection(conn):
        # Ensure schema resolution for every pooled connection
        await conn.execute("SET search_path TO todo_app, public")
    db_pool = await asyncpg.create_pool(DATABASE_URL, init=_init_connection, min_size=1, max_size=10)

@app.on_event("shutdown")
async def shutdown():
    # Close database connection pool when app shuts down
    if db_pool:
        await db_pool.close()

# --- 3. Pydantic models (data validation and serialization) ---
# Define the format of request/response data.

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    slack_channel: Optional[str] = None

class UserInDB(BaseModel):
    id: int
    email: EmailStr
    password_hash: str

class UserPublic(BaseModel):
    id: int
    email: EmailStr
    slack_channel: Optional[str] = None
    created_at: datetime

class Token(BaseModel):
    access_token: str
    token_type: str

class TodoBase(BaseModel):
    description: str
    due_date: datetime
    payload: Optional[dict] = None

class TodoCreate(TodoBase):
    pass

class TodoPublic(TodoBase):
    id: int
    user_id: int
    completed: bool
    created_at: datetime
    completed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class TodoUpdate(BaseModel):
    description: Optional[str] = None
    due_date: Optional[datetime] = None
    completed: Optional[bool] = None
    payload: Optional[dict] = None


# --- 4. Security and authentication utilities ---

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=ALGORITHM)
    return encoded_jwt

# --- Utility: normalize JSONB payload from DB ---
def _parse_payload_value(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text == "" or text.lower() == "null":
            return None
        try:
            return json.loads(text)
        except Exception:
            return None
    return value

def _coerce_todo_record(record) -> dict:
    data = dict(record)
    if 'payload' in data:
        data['payload'] = _parse_payload_value(data['payload'])
    return data

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    
    # Defensive: ensure search_path is correct for acquired connection, too
    async with db_pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        user_record = await conn.fetchrow("SELECT id, email, password_hash FROM users WHERE email = $1", email)
    
    if user_record is None:
        raise credentials_exception
    
    return UserInDB(**dict(user_record))


# --- 5. API routes (Endpoints) ---

# === 5.1 Authentication API ===
@app.post("/api/auth/register", response_model=UserPublic, status_code=status.HTTP_201_CREATED)
async def register_user(user: UserCreate):
    async with db_pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        existing_user = await conn.fetchval("SELECT id FROM users WHERE email = $1", user.email)
        if existing_user:
            raise HTTPException(status_code=400, detail="Email already registered.")
        
        password_hash = get_password_hash(user.password)
        
        new_user_record = await conn.fetchrow(
            """
            INSERT INTO users (email, password_hash, slack_channel)
            VALUES ($1, $2, $3)
            RETURNING id, email, slack_channel, created_at
            """,
            user.email, password_hash, user.slack_channel
        )
    return UserPublic.model_validate(dict(new_user_record))

@app.post("/api/auth/token", response_model=Token)
async def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    async with db_pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        user_record = await conn.fetchrow("SELECT * FROM users WHERE email = $1", form_data.username)

    if not user_record or not verify_password(form_data.password, user_record['password_hash']):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user_record['email']}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


# === 5.1 Root path ===
@app.get("/")
async def root():
    return {
        "message": "Slack Shared Todo Reminder API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "todos": "/api/todos",
            "auth": "/api/auth/token"
        }
    }

@app.get("/healthz")
async def healthz():
    # basic DB connectivity check too (non-fatal)
    try:
        async with db_pool.acquire() as conn:
            await conn.execute("SELECT 1")
        return {"ok": True, "db": "up"}
    except Exception:
        return {"ok": True, "db": "down"}

# === 5.2 Todos API ===
@app.post("/api/todos", response_model=TodoPublic, status_code=status.HTTP_201_CREATED)
async def create_todo(todo: TodoCreate, current_user: UserInDB = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        new_todo_record = await conn.fetchrow(
            """
            INSERT INTO todos (user_id, description, due_date, payload)
            VALUES ($1, $2, $3, $4)
            RETURNING *
            """,
            current_user.id, todo.description, todo.due_date, json.dumps(todo.payload) if todo.payload else None
        )
    return TodoPublic.model_validate(_coerce_todo_record(new_todo_record))

@app.get("/api/todos", response_model=List[TodoPublic])
async def get_todos(
    current_user: UserInDB = Depends(get_current_user),
    desc_search: Optional[str] = None, # description search term (pg_trgm)
    payload_search: Optional[str] = None # payload search term (FTS)
):
    query = "SELECT * FROM todos WHERE user_id = $1"
    params = [current_user.id]
    
    # Search for description using pg_trgm (ILIKE)
    if desc_search:
        query += f" AND description ILIKE ${len(params) + 1}"
        params.append(f"%{desc_search.strip()}%")
        
    # Search for payload using FTS (@@)
    if payload_search:
        query += f" AND to_tsvector('simple', payload::text) @@ websearch_to_tsquery('simple', ${len(params) + 1})"
        params.append(payload_search.strip())
        
    query += " ORDER BY due_date ASC"

    async with db_pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        todo_records = await conn.fetch(query, *params)
        
    return [TodoPublic.model_validate(_coerce_todo_record(record)) for record in todo_records] # Pydantic v2

@app.get("/api/todos/{todo_id}", response_model=TodoPublic)
async def get_todo_by_id(todo_id: int, current_user: UserInDB = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        todo_record = await conn.fetchrow(
            "SELECT * FROM todos WHERE id = $1 AND user_id = $2",
            todo_id, current_user.id
        )
    if not todo_record:
        raise HTTPException(status_code=404, detail="Todo not found.")
    return TodoPublic.model_validate(_coerce_todo_record(todo_record))

@app.patch("/api/todos/{todo_id}", response_model=TodoPublic)
async def update_todo(todo_id: int, todo_update: TodoUpdate, current_user: UserInDB = Depends(get_current_user)):
    update_data = todo_update.model_dump(exclude_unset=True, exclude_none=True) # Pydantic v2
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No update content.")

    # Set 'completed_at' when 'completed' status changes
    if 'completed' in update_data:
        update_data['completed_at'] = datetime.now(timezone.utc) if update_data['completed'] else None

    # Convert payload dict to JSON string for JSONB column
    if 'payload' in update_data and update_data['payload'] is not None:
        update_data['payload'] = json.dumps(update_data['payload'])

    set_clauses = [f"{key} = ${i+2}" for i, key in enumerate(update_data.keys())]
    query = f"UPDATE todos SET {', '.join(set_clauses)} WHERE id = $1 AND user_id = ${len(update_data) + 2} RETURNING *"
    
    params = [todo_id] + list(update_data.values()) + [current_user.id]

    async with db_pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        updated_record = await conn.fetchrow(query, *params)

    if not updated_record:
        raise HTTPException(status_code=404, detail="Todo not found or no permission to update.")
    return TodoPublic.model_validate(_coerce_todo_record(updated_record))

@app.delete("/api/todos/{todo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_todo(todo_id: int, current_user: UserInDB = Depends(get_current_user)):
    async with db_pool.acquire() as conn:
        await conn.execute("SET search_path TO todo_app, public")
        result = await conn.execute(
            "DELETE FROM todos WHERE id = $1 AND user_id = $2",
            todo_id, current_user.id
        )
    # Parse the number from "DELETE 1"
    if int(result.split(' ')[1]) == 0:
        raise HTTPException(status_code=404, detail="Todo not found or no permission to delete.")
    return None

# Simple entry point for running the server
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
